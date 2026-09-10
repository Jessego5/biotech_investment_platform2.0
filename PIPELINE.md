# Pipeline

How BioBase is built, in the order it has to happen, with what
each stage costs and what it gets wrong. Rebuilding from nothing takes about six hours,
most of it waiting on SEC and OpenAI.

Everything runs through the `ingest` service in `docker-compose.yml`, which is
in the `batch` profile so it is not started by `docker compose up`.

```bash
docker compose run --rm --build \
  -e SEC_USER_AGENT="$SEC_UA" -e OPENAI_API_KEY="$OAI" \
  ingest python -u <script>.py [flags]
```

**Two things that will waste a run before you notice.** `docker compose run`
uses the built image and there is no source bind mount, so a code change needs
`--build`, without it a script silently runs the last image and reports
success. And `SEC_USER_AGENT` contains a space; extracting it from `.env`
through an `xargs` pipeline truncates it and every SEC request 403s while the
run exits 0. Read it with `sed -n 's/^SEC_USER_AGENT=//p' backend/.env`.

---

## Order

Stages 1–3 must run in this order. After that the branches are independent.

| # | Stage | Script | Time | Needs |
|---|---|---|---|---|
| 1 | Company universe | `build_company_universe.py` | ~20 min | SEC |
| 2 | Trials + financials | `ingest.py` | ~1 h | SEC, CTG |
| 3 | Wider registry | `ingest_registry.py` | ~40 min | CTG |
| 4 | Subsidiary aliases | `build_aliases.py` | ~50 min | SEC |
| 5 | Registry linkage | `link_registry.py` | ~2 min |, |
| 6 | Missing trials | `backfill_trials.py` | ~15 min | CTG |
| 7 | Financial history | `backfill_financials.py` | ~15 min | SEC |
| 8 | FDA Orange Book | `ingest_orange_book.py` | ~5 min | download |
| 9 | FDA Purple Book | `ingest_purple_book.py` | ~2 min | download |
| 10 | Trial embeddings | `embed_trials.py` | ~25 min | OpenAI |
| 11 | Filing text | `embed_filings.py --history 5` | ~2 h | SEC, OpenAI |

**4 before 6.** `backfill_trials` resolves subsidiaries through the alias table;
run it first and it finds less and tells you nothing is wrong.

**2 before 11.** `embed_filings` reads `companies.cik`, so an empty companies
table means it does nothing and says so as though it were finished.

### The ordering mistake that cost a full run

Ingestion was once started against an empty Postgres before the aliases and
registry were migrated into it. 442 companies were written before anyone noticed
Eli Lilly had returned zero trials, the matching rules were reading an alias
table that did not exist yet, so every subsidiary silently failed to resolve and
the run reported success throughout. **Seed and migrate first, then ingest.**

---

## What each stage is

**1. `build_company_universe.py`**, sweeps EDGAR's SIC codes for pharma,
biotech and medical devices and writes `backend/companies.json`. Everything else
reads that file. → **787 companies**

**2. `ingest.py`**, per company, one ClinicalTrials.gov sponsor search and one
SEC `companyfacts` request, archived to a dated snapshot and written to
`trials` and `financials`. `--tickers A,B,C` re-runs named companies, which is
what a matching-rule change needs; `--shard N --of M` splits the run;
`--snapshot-only` archives without writing.
→ **30,823 trials, 42,348 financial rows**

`INGEST_WORKERS` is a memory setting as much as a speed one. Each worker can
hold a sponsor's entire response, up to a thousand studies, so eight at once
was killed by the OOM reaper at company 53 of 787 in a 3.8 GB VM also running
Postgres. Compose sets 3.

**3. `ingest_registry.py`**, every industry-sponsored interventional study,
not only those of companies we track. This is what makes "who else is developing
for this indication" answerable, and it is what `backfill_trials` looks up names
in. → **112,812 studies**

**4. `build_aliases.py`**, Exhibit 21 to each 10-K, which is a company's own
annual statement of what it owns. `--years N` reads back that many years.
→ **49,822 aliases**

Only the newest year is used for matching. Exhibit 21 is a statement about one
year: Illumina listed GRAIL through 2024 and spun it off, and reading every year
at once gave Illumina eight trials belonging to a company that files its own
10-K here. 264 companies hold an alias that has dropped out of their latest
filing.

**5. `link_registry.py`**, resolves registry sponsors to tickers using the same
rules as everything else. `--dry-run` reports without writing. Most of the
registry stays unlinked and that is the point: a null means "not a company we
track", which is different from "not a company".

**6. `backfill_trials.py`**, the trials a company runs under a name the sponsor
search never asks for. Autolus Therapeutics registers as "Autolus Limited" and a
search for the filing name returns nothing, so no rule ever gets to judge it.
Falls back to fetching by NCT id, because the sponsor search can miss the name
you hand it: "Bio-Path Holdings, Inc." returns two studies belonging to LS
BioPath. `--dry-run` first.

**7. `backfill_financials.py`**, ten years per metric instead of one, from the
same `companyfacts` response already being fetched. Costs no extra requests.

**8–9. FDA**, Orange Book (small molecules, patents and exclusivity) and Purple
Book (biologics, exclusivity only). Only 112 of 787 companies have an approved
product; that is the universe being clinical-stage, not a gap.
→ **48,664 products, 22,205 patents, 2,230 biologics**

**10–11. Embeddings**, `text-embedding-3-small`, 1536 dimensions. Filings are
five years of annual reports per company. `embed_filings` has the most flags
because extraction is the part that keeps being wrong:

| Flag | For |
|---|---|
| `--history N` | N most recent annual reports per company |
| `--missing-section NAME` | only filings that yielded no NAME |
| `--oversized-section mdna:120000` | only filings where NAME is too big |
| `--tickers A,B` | named companies |
| `--stamp-periods` | fill `period_end`/`fiscal_year` without re-reading |
| `--refresh` | re-read everything |

→ **3,614 filings, 334,624 chunks**

---

## Snapshots, and taking them on a schedule

A snapshot is what the APIs returned on a date. Two of them taken by the same
code are the only thing that can answer "what changed"; nothing else produces
that, and no amount of re-reading today's data will.

```bash
./snapshot.sh          # take one if today has none
./snapshot.sh --force  # take one regardless
```

It runs `ingest.py --snapshot-only`, which archives without writing to the
database, so a scheduled run can never disturb what the app is serving.

**Weekly, not daily.** About 1% of the trials in this universe start in a given
month, 334 of 30,823 in August. A daily run spends roughly 1,574 API requests
to capture almost nothing and fills the archive with dates that differ from each
other by rounding. `snapshot.plist` is a launchd job for Mondays at 07:00:

```bash
cp snapshot.plist ~/Library/LaunchAgents/com.biotechagent.snapshot.plist
launchctl load ~/Library/LaunchAgents/com.biotechagent.snapshot.plist
```

The AWS path is deployed and the schedule is off. `infra/cloudformation/
pipeline.yaml` carries an EventBridge rule, `rate(7 days)` for dev and
`cron(0 6 * * ? *)` for prod, and both ship `DISABLED`: the task it starts reads
an ingest image from ECR that `serve.sh` does not push, so an enabled schedule
would fire daily into a tag nothing had put there. Push the image, set
`ScheduleState: ENABLED` for prod, update the stack.

### What the script refuses to do quietly

An unattended run that fails silently is worse than no run, because the gap
looks like a quiet week. So it exits non-zero, loudly, when:

- `SEC_USER_AGENT` is missing or short. It contains a space, and reading it
  through an `xargs` pipeline truncates it to the first word, after which every
  SEC request 403s while the run exits 0.
- fewer than 700 of about 787 companies were archived. A run that exits 0 having
  fetched almost nothing is the failure this project keeps meeting: silent, and
  shaped like success.

It also refuses to take a second snapshot of the same day unless forced. Two
snapshots hours apart are not a period of time.

### Every run writes a manifest

Written before fetching, so an interrupted run still says what it was: the
commit, the company count, and whether it covered the whole universe.

This exists because a diff cannot otherwise tell the world changing from us
changing. Comparing the first two snapshots reported Church & Dwight registering
34 trials in four days, one of them a benzocaine study from 2007, it had always
run them, and the matching rules had changed. `/changes` reports the provenance
and says plainly when two ends are not comparable.

`latest_pair` also skips partial runs when choosing the newest snapshot. A
targeted `--tickers` re-ingest archives only what it touched, and comparing the
universe against 48 companies reported 739 as "not in both". A run that says it
was partial is a repair, not a period of time.

---

## Deploying to Postgres

`migrate_to_postgres.py` copies the tables that are correct and expensive to
rebuild, registry, aliases, filings, chunks, from local SQLite. `--dry-run`
first. Seed companies before migrating anything that references them.

---

## What is easy to get wrong

**A resume check that asks an easier question than the one that matters.** This
happened twice in one day. `backfill_financials` counted distinct fiscal years
*across* metrics, so a company with cash in FY2025 and revenue in FY2024 looked
finished, and 715 of 780 companies were skipped. `embed_filings --history 5`
asked whether a company had *a* filing, skipped all 776 for having the one they
already had, and reported success having read eleven. Both exited 0 with a
summary line that read like success. **A resume test has to describe the
finished state, not merely a state that is no longer empty.**

**Changing what a table holds without re-reading what reads it.** Storing ten
years of financials broke `metrics_from_db`, which built `{metric: figure}` from
an unordered list, correct with one row per metric, and with ten it kept
whatever row the iteration ended on, a different year per company with nothing
to say so. Storing five years of filings would have let `search_filings` answer
from 2021 as though it were current.

**A section that is too large is as wrong as one that is missing, and it does
not show up as a gap.** Twenty-three filings had management discussions of
300,000 to 600,000 characters, most of the filing, not a section of it, every
one starting at a cross-reference. Nothing had ever pointed at them because they
were not missing anything and only absence was being looked for. That is what
`--oversized-section` exists for.

**A relevance floor calibrated on the wrong corpus.** `MIN_SCORE = 0.40` was
measured against trials, which are short and titled like questions. A filing
passage is 3,000 characters of dense prose and scores lower for saying the same
thing. That floor sat in the middle of the *on-topic* distribution rather than
above the off-topic one, and hid the intellectual property section of 168 of the
745 companies that have one. Off-topic questions top out at 0.272; on-topic
medians are 0.40 to 0.54; the filing floor is 0.30.

**Before recording that a filing lacks a section, look at its table of
contents.** It says what the filing calls things. I claimed companies had no
intellectual property section four times and was wrong every time, Johnson &
Johnson's contents page reads "Raw materials 3 Patents 3 Trademarks 3". The same
rule caught the opposite error later: Electromed *declines* Item 1A in the text,
and what was being stored as its risk factors was the cybersecurity disclosure.

**Loosening a matching rule is how a company ends up with someone else's
pipeline.** Substring containment once put 61 Merck KGaA trials into Merck & Co
and 355 Nova Scotia and university studies into a semiconductor company. Every
rule since is an identity rather than a resemblance, and every widening is swept
across all 787 companies against all 112,812 studies before it is trusted. The
distinctiveness threshold is six letters because six is what that sweep
measured; eight was a guess.

**An index is only as good as its claim about what it is allowed to skip.** The
first-word index in `backfill_trials` assumed every rule needs the first word to
agree. That was true when it was written and false an hour later: "TheRas, Inc.,
d/b/a BBOT (BridgeBio Oncology Therapeutics)" files under "theras", BridgeBio
looks under "bridgebio", and the rule written to join them worked perfectly in
isolation while the company stayed empty.

---

## Checking the result

```sql
-- companies with no trials: should be 0
SELECT count(*) FROM companies c
WHERE NOT EXISTS (SELECT 1 FROM trials t WHERE t.company_ticker = c.ticker);

-- a fetch that never returned, recorded as absence
SELECT ticker FROM companies WHERE trial_count_total IS NULL;

-- sections too big to be sections
SELECT count(*) FROM filings WHERE mdna_chars > 120000;

-- chunks that were stored but never embedded
SELECT count(*) FROM filing_chunks WHERE embedding IS NULL;
```

`evaluate.py` runs the groundedness suite over the fixed question set in
`eval_questions.py`.

---

## Repair

`migrate_trial_fields.py` fills trial fields that were being fetched and thrown
away, from the registry table already held, worth reading before adding a
field, because it is the pattern for backfilling one without a full re-ingest.

Recovering a run that dropped its connection partway is a local concern rather
than a stage of the pipeline: re-run `ingest.py --tickers` with the companies
that failed. Every company row is an upsert, so re-running one that already
landed rewrites it rather than duplicating it.
