"""
This file grabs the real data for each company, the clinical trials from
ClinicalTrials.gov and the financials from SEC EDGAR. It only works for public
companies since those are the ones with real filings.
"""

import os
import re
import threading
import time

import requests

# load backend/.env so SEC_USER_AGENT is picked up even when a script imports this
# directly, not just through the API
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

# SEC wants automated requests to identify themselves with a real contact email.
# set SEC_USER_AGENT in your .env (see .env.example); the default is a placeholder.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "biotech-agent your-real-email@example.com")

# SEC allows at most about 10 requests per second. when ingestion runs several
# companies in parallel, that ceiling is shared across all the threads, so gate
# every SEC request through one rate limiter (about 0.12s apart, roughly 8 per
# second) and retry when we get a 429.
_sec_lock = threading.Lock()
_sec_last = [0.0]
# about 6 to 7 requests per second, very under SEC's 10 per second cap
_SEC_MIN_INTERVAL = 0.15


def _sec_get(url, params=None):
    """GET an SEC URL, rate-limited across threads, retrying a few times on 429."""
    # try up to four times so a throttle doesn't kill the request outright
    for attempt in range(4):
        # only one thread at a time checks the clock and updates the last-call time
        with _sec_lock:
            # figure out how long we still need to wait before the next allowed call
            wait = _SEC_MIN_INTERVAL - (time.monotonic() - _sec_last[0])
            if wait > 0:
                time.sleep(wait)
            # record the time of this call so the next one paces off it
            _sec_last[0] = time.monotonic()
        r = requests.get(url, params=params,
                         headers={"User-Agent": SEC_USER_AGENT}, timeout=30)
        # a 429 means we got throttled, so back off a bit and try again
        if r.status_code == 429:
            # wait longer on each successive attempt
            time.sleep(1.0 * (attempt + 1))
            continue
        return r
    return r

# corporate suffixes to ignore when matching a company name to a trial sponsor.
# ie same company may have slightly different names (suffixes mostly)
# this lets "FATE THERAPEUTICS INC" (the SEC legal name) match a lead sponsor of
# "Fate Therapeutics" without the "INC" throwing off the substring check.
_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company",
             "llc", "ltd", "limited", "plc", "ag", "sa", "nv", "holdings"}


def _core_name(name):
    """Lowercase a company name and drop punctuation + trailing corp suffixes."""
    # lowercase each word and strip out everything that isn't a letter or number
    words = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in name.split()]
    # drop any words that came out empty after stripping
    words = [w for w in words if w]
    # peel off trailing corporate suffixes like "inc" or "corp"
    while words and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words)


def _search_term(name):
    """
    Clean a company name into a good ClinicalTrials.gov sponsor query. Keeps the
    real words (and their casing) but drops punctuation and trailing corporate
    suffixes. The ", Inc." on a SEC legal name makes the sponsor search miss
    (e.g. "Fate Therapeutics, Inc." finds nothing, "Fate Therapeutics" finds it).
    """
    # strip punctuation from each word but keep the original casing this time
    words = [re.sub(r"[^A-Za-z0-9]", "", w) for w in name.split()]
    # drop any words that came out empty
    words = [w for w in words if w]
    # peel off trailing corporate suffixes
    while words and words[-1].lower() in _SUFFIXES:
        words.pop()
    # fall back to the original name if stripping left us with nothing
    return " ".join(words) or name

CT_BASE = "https://clinicaltrials.gov/api/v2/studies"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_CONCEPT = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"

# multiple candidate tags, since companies report under different XBRL tags.
# 10x Genomics, for example, only reports the "excluding acquired IPR&D" variant.
RD_TAGS = [
    "ResearchAndDevelopmentExpense",
    "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
]
CASH_TAGS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
]


# - ClinicalTrials.gov
def _trial_text(ps):
    """
    Build the free-text blob we embed for semantic search: brief summary,
    conditions, interventions, and eligibility. These are the fields the
    structured columns can't answer over (mechanisms, mutations, therapies).
    Capped in length to keep embeddings focused and cheap.
    """
    parts = []
    # grab the brief summary and add it if it exists
    summary = ps.get("descriptionModule", {}).get("briefSummary", "")
    if summary:
        parts.append(summary)
    # add the list of conditions the trial studies
    conditions = ps.get("conditionsModule", {}).get("conditions", [])
    if conditions:
        parts.append("Conditions: " + ", ".join(conditions))
    # pull out the names of the interventions and add the ones that have a name
    interventions = ps.get("armsInterventionsModule", {}).get("interventions", [])
    names = [i.get("name", "") for i in interventions if i.get("name")]
    if names:
        parts.append("Interventions: " + ", ".join(names))
    # add the eligibility criteria text
    eligibility = ps.get("eligibilityModule", {}).get("eligibilityCriteria", "")
    if eligibility:
        parts.append(eligibility)
    # join it all together and cap the length to keep the embedding focused and cheap
    return "\n".join(parts)[:2000]


def fetch_trials(sponsor_name, page_size=100):
    """
    Fetch trials for a sponsor. Returns a list of flattened trial dicts,
    filtered to those whose lead sponsor actually matches (avoids the
    Illumina-style over-matching where the search pulls in unrelated orgs).
    """
    # search ClinicalTrials.gov by sponsor, cleaning the name so ", Inc." doesn't blank it
    resp = requests.get(CT_BASE, params={
        "query.spons": _search_term(sponsor_name),
        "pageSize": page_size,
        "countTotal": "true",
    }, timeout=30)
    resp.raise_for_status()
    studies = resp.json().get("studies", [])

    trials = []
    # loop through each study the search returned
    for s in studies:
        # dig into the nested modules that hold the fields we want
        ps = s.get("protocolSection", {})
        idm = ps.get("identificationModule", {})
        stm = ps.get("statusModule", {})
        dsm = ps.get("designModule", {})
        spm = ps.get("sponsorCollaboratorsModule", {})
        lead = spm.get("leadSponsor", {}).get("name", "")

        # sponsor filter: keep only the trials this company actually leads.
        # compare on the "core" name (suffixes stripped) so "Recursion" matches
        # "Recursion Pharmaceuticals Inc." and "FATE THERAPEUTICS INC" matches
        # "Fate Therapeutics", while still dropping trials led by a different org.
        if _core_name(sponsor_name) not in _core_name(lead):
            continue

        # flatten the fields we care about into a simple trial dict
        trials.append({
            "nct_id": idm.get("nctId"),
            "title": idm.get("briefTitle"),
            "status": stm.get("overallStatus"),
            "phase": ", ".join(dsm.get("phases", []) or []) or "N/A",
            "lead_sponsor": lead,
            # the free-text blob used later for semantic search
            "summary": _trial_text(ps),
        })
    return trials


def summarize_pipeline(trials):
    """Turn a trial list into pipeline signal: counts by phase and status."""
    by_phase, by_status = {}, {}
    # tally up how many trials fall under each phase and each status
    for t in trials:
        by_phase[t["phase"]] = by_phase.get(t["phase"], 0) + 1
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1
    # a trial counts as active if it is recruiting or otherwise still running
    active = sum(1 for t in trials
                 if t["status"] in ("RECRUITING", "ACTIVE_NOT_RECRUITING",
                                     "ENROLLING_BY_INVITATION"))
    # terminated trials are the ones marked TERMINATED
    terminated = by_status.get("TERMINATED", 0)
    return {
        "total_trials": len(trials),
        "by_phase": by_phase,
        "by_status": by_status,
        "active_trials": active,
        "terminated_trials": terminated,
    }


# - SEC EDGAR
_ticker_map = None
_name_map = None

def _load_ticker_map():
    global _ticker_map
    # only fetch and build the map once, then reuse it
    if _ticker_map is None:
        r = _sec_get(SEC_TICKERS)
        r.raise_for_status()
        # map each ticker to its 10-digit zero-padded CIK
        _ticker_map = {row["ticker"].upper(): f"{int(row['cik_str']):010d}"
                       for row in r.json().values()}
    return _ticker_map


def company_name(ticker):
    """
    Look up a company's name from SEC's ticker file. Used by the API's live
    fallback so we can analyze a ticker that isn't in our sourced universe yet.
    """
    global _name_map
    # build the ticker to name map once, then reuse it
    if _name_map is None:
        r = _sec_get(SEC_TICKERS)
        r.raise_for_status()
        _name_map = {row["ticker"].upper(): row["title"] for row in r.json().values()}
    return _name_map.get(ticker.upper())


# annual-report forms: US companies file a 10-K, foreign private issuers
# (like BioNTech) file a 20-F. accept both so foreign biotechs aren't blanked out.
ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "20-F/A")


def _latest_annual(cik, tags):
    """
    Return the most recent annual value across ALL candidate tags.

    Important: we scan every tag and keep the newest fiscal year, instead of
    returning the first tag that happens to have data. A company that switched
    which XBRL tag it reports cash under (Illumina did) would otherwise get
    stuck on a stale year from the abandoned tag.
    
    """
    best = None
    # check every candidate tag, not just the first that has data
    for tag in tags:
        r = _sec_get(SEC_CONCEPT.format(cik=cik, tag=tag))
        # a 404 just means this company doesn't report under this tag, so skip it
        if r.status_code == 404:
            continue
        r.raise_for_status()
        # walk every reported entry under this tag
        for _, entries in r.json().get("units", {}).items():
            for e in entries:
                # only keep full-year figures that came from an annual report form
                if e.get("fp") == "FY" and e.get("form") in ANNUAL_FORMS:
                    # hold onto this one if it is the newest fiscal year seen so far
                    if best is None or e.get("fy", 0) > best["fiscal_year"]:
                        best = {"value": e["val"], "fiscal_year": e["fy"], "tag": tag}
    return best


def fetch_financials(ticker):
    """
    Return real financials for a public company, or a reason it's unavailable.
    Keyed by CIK (resolved from ticker).
    """
    # resolve the ticker to a CIK, which is how EDGAR keys everything
    cik = _load_ticker_map().get(ticker.upper())
    if not cik:
        # a company that got acquired or delisted (Verve, bought by Lilly) drops
        # out of EDGAR's ticker file even though its old trials still exist.
        return {"available": False, "reason": f"ticker {ticker} not found in EDGAR"}

    # pull the most recent annual R&D expense and cash figures
    rd = _latest_annual(cik, RD_TAGS)
    cash = _latest_annual(cik, CASH_TAGS)

    # if both come back empty, the company almost certainly files under IFRS
    # (foreign private issuers like BioNTech file a 20-F with ifrs-full tags,
    # not us-gaap), so say that plainly instead of showing a blank.
    if rd is None and cash is None:
        return {
            "available": False,
            "cik": cik,
            "reason": "no us-gaap annual figures; likely a foreign issuer "
                      "reporting under IFRS (not parsed by this tool)",
        }

    return {"available": True, "cik": cik, "rd_expense": rd, "cash": cash}