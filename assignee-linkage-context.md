# Patent → Company Linkage for US-Listed Clinical-Trial Sponsors

Project context. Read this before writing pipeline code.

## Goal

Link US patents to the US-listed companies that own them, for a universe of
companies defined by having industry-sponsored trials on ClinicalTrials.gov and
a CIK/ticker on SEC EDGAR.

The core difficulty: one company's patents appear under many different assignee
strings, because of (a) name variants of the same legal entity and (b) genuinely
different legal entities under one corporate parent. These need different fixes.

## Why this scope is tractable

We have a fixed reference list of target companies. That turns the problem from
unsupervised clustering over ~8M assignee strings into record linkage against a
few hundred known targets. Much higher achievable precision.

It also means every company in the universe is an SEC filer by construction, so
Exhibit 21 subsidiary lists are available. That closes the corporate-hierarchy
gap that has no good free general-purpose solution.

## Canonical key

Key everything on **CIK**. Not ticker.

Biotech tickers change constantly via reverse mergers, rebrands and delistings.
CIK persists across all of it.

---

## Data sources

| Source | URL | Use |
|---|---|---|
| SEC ticker/CIK map | `https://www.sec.gov/files/company_tickers.json` | Universe seed |
| EDGAR filings | `https://www.sec.gov/cgi-bin/browse-edgar` / submissions JSON API | 10-K retrieval |
| Exhibit 21 | Attachment to each 10-K | Subsidiary → parent map, dated |
| AACT | `https://aact.ctti-clinicaltrials.org` | ClinicalTrials.gov as PostgreSQL, daily refresh |
| PatentsView | `https://data.uspto.gov` (migrated from patentsview.org, March 2026) | Disambiguated assignee IDs |
| FDA Orange Book | `https://www.fda.gov/drugs/drug-approvals-and-databases/orange-book-data-files` | Validation set |
| USPTO Assignment Data | USPTO bulk data | Post-grant transfers, optional |

Notes:

- **PatentsView** provides `g_assignee_disambiguated` (persistent `assignee_id`),
  `g_assignee_not_disambiguated` (raw strings), and `g_persistent_assignee`
  (old ID → current ID, needed if you ever join across releases).
- **AACT** has a `ctgov` schema plus separate project schemas. The **CDEK**
  schema contains prior organization-name disambiguation work on ct.gov
  sponsors. Check it before rebuilding sponsor normalization from scratch.
- **Orange Book** `patent.txt` maps patent number → NDA number; `products.txt`
  carries `Applicant_Full_Name`. Join gives patent → company. Small molecules
  only.
- **Purple Book** is not useful for patents. BPCIA does not require reference
  product sponsors to list them; roughly 2% of biologic listings have any patent
  info. Do not plan around it.

---

## Pipeline

### 1. Build the universe

From `company_tickers.json`, filter to SIC 2834 (pharma preparations),
2836 (biological products), 8731 (commercial physical & biological research).

Output: `companies(cik, ticker, name, sic)`

### 2. Build the subsidiary map

For each CIK, pull every 10-K and parse Exhibit 21.

Critical: take the **union across all filing years**, not just the latest.
Entities that were acquired and then dissolved appear only in the years between.
If you use the latest snapshot you silently drop them, and those are exactly the
acquired companies whose trials and patents you're trying to attribute.

Output: `subsidiaries(cik, subsidiary_name, jurisdiction, fiscal_year)`

Known gaps: no coverage of pre-IPO years, and small subsidiaries fall below the
materiality threshold and never get listed.

### 3. Trials

```sql
SELECT s.nct_id, s.name, s.agency_class, s.lead_or_collaborator
FROM sponsors s
WHERE s.agency_class = 'INDUSTRY';
```

Do **not** filter to `lead_or_collaborator = 'lead'` only. Industry-funded trials
run by a university list the university as lead sponsor and the company as a
collaborator. Lead-only filtering drops real company involvement.

Sponsor strings have the same variant problem as assignees. Trials registered
before an acquisition keep the target's name permanently; AACT does not backfill.
Resolve against the same subsidiary map.

### 4. Patents

Pull PatentsView disambiguated assignees. Match `assignee_organization` to the
subsidiary map.

Matching approach: normalize (Unicode NFKC → uppercase → strip punctuation →
strip legal suffixes via `cleanco` → collapse whitespace), then block on
character 3-gram TF-IDF + ANN, then score with n-gram cosine + Jaro-Winkler.
`splink` if you want a probabilistic model instead of hand-tuned thresholds.

Because we're matching against a known list, favour high precision. Set the
threshold conservatively and hand-review the near-misses; the near-miss set is
small at this universe size.

Tie-break signals when name similarity is ambiguous: shared inventors (strongest),
assignee address/city, CPC class overlap, attorney of record.

### 5. Validate

Join Orange Book `patent.txt` → `products.txt` → your CIK mapping. That is a free
labeled set. Measure pairwise precision/recall against it.

Caveat: Orange Book skews toward approved small molecules, so measured
performance will **overstate** performance on the full universe, especially on
clinical-stage biotech with no approvals.

---

## Both sides resolve through the same map

```
ct.gov lead_sponsor ──┐
ct.gov collaborator ──┼──> Exhibit 21 subsidiary union ──> CIK ──> ticker
PatentsView assignee ─┘
```

Build the subsidiary map first. Everything else depends on it.

---

## Open problems

### Licensed-in university IP (highest priority)

A large share of clinical-stage biotech runs on patents assigned to a university
or research institute and exclusively licensed to the company. The assignee field
says "The Regents of the University of California"; the commercial owner is the
ticker.

There is no structured dataset for this. It lives in 10-K Item 1 and S-1
risk-factor prose. Extraction is a text-mining task, not a join. Bayh-Dole
government interest statements on the patents are a partial signal.

Ignoring this biases results toward older companies with in-house research and
against licensing-driven startups. If the analysis is about innovation output,
this gap is not optional.

### Residual unmatched sponsors

Sponsors that match nothing in the Exhibit 21 union: private companies, foreign
parents, entities acquired before the acquirer's filing history covers them.
Small enough to hand-resolve. Won't resolve itself.

### No assignee evaluation benchmark

PatentsView-Evaluation is inventor-focused. Orange Book is the best available
proxy for assignees and it's biased as noted above.

---

## Decisions to make explicitly

Record the answers in the repo. Silently mixing conventions is the most common
way this analysis goes wrong.

1. **Ownership as of grant date, or as of today?**
   A patent assigned to a company in 2015 that was acquired in 2019 has two
   defensible answers. Pick one. Affects every time series.

2. **Do collaborator-role trials count as company involvement, or lead only?**

3. **Does licensed-in IP count as the company's patent, or only assigned IP?**

---

## Suggested schema

```
companies(cik PK, ticker, name, sic)
subsidiaries(cik FK, subsidiary_name, jurisdiction, fiscal_year)
trials(nct_id PK, sponsor_name_raw, agency_class, role, cik FK, match_score, match_method)
patents(patent_id PK, assignee_id, assignee_org_raw, grant_date, cik FK, match_score, match_method)
orange_book(patent_no, appl_no, applicant_full_name, cik FK)
match_review(entity_type, raw_string, proposed_cik, score, human_verdict)
```

Carry `match_score` and `match_method` on every linked row. Never overwrite the
raw string with the resolved name; keep both so matches stay auditable.

---

## Anti-patterns

- Keying on ticker instead of CIK.
- Using only the latest Exhibit 21 instead of the multi-year union.
- Filtering ct.gov sponsors to lead-only.
- Rebuilding assignee disambiguation from scratch instead of using PatentsView
  `assignee_id`.
- All-pairs string comparison without blocking.
- Reporting counts without stating the ownership-date convention.
- Treating Orange Book validation performance as representative of the full set.
