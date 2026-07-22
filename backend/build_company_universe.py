"""
This script builds the company list instead of me typing one by hand. It asks
SEC EDGAR which companies file under the biotech SIC codes, maps each one to a
ticker and name from SEC's ticker file, and keeps only the ones that really have
both a trial pipeline on ClinicalTrials.gov and real financials on EDGAR. That
drops the shells, holding companies, and firms with no clinical pipeline. The
survivors get written to companies.json for the app to load. It does a full
sweep, paging through every company in each SIC code, then checks trials and
financials for every candidate in parallel since those are independent network
calls. Run it with python build_company_universe.py, and set SEC_USER_AGENT to
your own email first.
"""

import os
import requests
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# load backend/.env so SEC_USER_AGENT is picked up when running this directly
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

# set SEC_USER_AGENT to your own real email in .env (see .env.example)
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "biotech-agent your-real-email@example.com")

# how many candidates to check at once. SEC asks for 10 or fewer requests per
# second, and each candidate makes a couple, so keep this modest.
WORKERS = 8

# Biotech / pharma SIC codes (2836 biologicals, 2834 pharma prep,
# 8731 commercial physical & biological research). The labels double as the
# "sector" we store for each company, so the frontend can filter by it.
SIC_CODES = ["2836", "2834", "8731"]
SIC_LABELS = {
    "2836": "Biologics",
    "2834": "Pharma preparations",
    "8731": "Bio research",
}

BROWSE = "https://www.sec.gov/cgi-bin/browse-edgar"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
CT_BASE = "https://clinicaltrials.gov/api/v2/studies"
SEC_CONCEPT = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"

HEADERS = {"User-Agent": SEC_USER_AGENT}

# the same R&D tags the app uses. some companies only report the "excluding IPR&D" one
RD_TAGS = [
    "ResearchAndDevelopmentExpense",
    "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
]

# corporate suffixes we strip when matching a company name to a trial's sponsor
SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company",
            "llc", "ltd", "limited", "plc", "ag", "sa", "nv", "holdings"}


def _get(url, params=None):
    """GET with one retry if SEC (or CT) throttles us with 403/429."""
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    # a 403 or 429 means we got throttled, so wait a second and try once more
    if r.status_code in (403, 429):
        time.sleep(1.0)
        r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    return r


def ciks_in_sic(sic):
    """
    Pull ALL CIKs for a SIC code, paging through EDGAR's browse endpoint. It only
    returns 100 per request, so we bump the `start` offset until a page comes back
    short (that's the end).
    Heads up: the atom feed's company-name fields come back as broken
    'ARRAY(0x...)' strings (a bug on SEC's side), so we grab only the CIKs here
    and get the real names from the ticker file instead.
    """
    ciks = []
    start = 0
    # keep paging until a short page tells us we've reached the end
    while True:
        # ask for the next 100 companies under this SIC, starting at the offset
        params = {
            "action": "getcompany", "SIC": sic, "type": "10-K",
            "dateb": "", "owner": "include", "count": 100, "start": start,
            "output": "atom",
        }
        r = _get(BROWSE, params)
        r.raise_for_status()
        # pull the zero-padded CIKs straight out of the atom feed
        page = [f"{int(c):010d}" for c in re.findall(r"<cik>(\d+)</cik>", r.text)]
        ciks += page
        # a page shorter than 100 means there are no more, so stop
        if len(page) < 100:
            break
        # move the offset to the next page
        start += 100
        # be polite and pause briefly between pages
        time.sleep(0.2)
    return ciks


_ticker_file = None
def load_ticker_file():
    """CIK -> {ticker, name} from SEC's ticker file (loaded once)."""
    global _ticker_file
    # load and build the map only once
    if _ticker_file is None:
        r = requests.get(SEC_TICKERS, headers=HEADERS, timeout=30)
        r.raise_for_status()
        # key each entry by its zero-padded CIK, keeping the ticker and name
        _ticker_file = {
            f"{int(v['cik_str']):010d}": {"ticker": v["ticker"].upper(),
                                          "name": v["title"]}
            for v in r.json().values()
        }
    return _ticker_file


def _first_core_word(name):
    """First meaningful word of a name, lowercased and stripped of punctuation."""
    # walk the words and return the first real one that isn't a corporate suffix
    for word in name.split():
        w = re.sub(r"[^a-z0-9]", "", word.lower())
        if w and w not in SUFFIXES:
            return w
    return ""


def _search_term(name):
    """
    Clean a name into a good ClinicalTrials.gov sponsor query, keep the words,
    drop punctuation and trailing corporate suffixes. Without this, searching the
    full SEC legal name ("Fate Therapeutics, Inc.") misses trials that a clean
    "Fate Therapeutics" finds.
    """
    # strip punctuation from each word, keep the ones that survive
    words = [re.sub(r"[^A-Za-z0-9]", "", w) for w in name.split()]
    words = [w for w in words if w]
    # peel off trailing corporate suffixes
    while words and words[-1].lower() in SUFFIXES:
        words.pop()
    # fall back to the original name if nothing is left
    return " ".join(words) or name


def has_trials(name):
    """True if this company actually leads at least one registered trial."""
    try:
        # search ClinicalTrials.gov by the cleaned sponsor name
        r = _get(CT_BASE, {"query.spons": _search_term(name), "pageSize": 20})
        r.raise_for_status()
        # match on the first meaningful word so "MODERNA, INC." lines up with a
        # lead sponsor like "ModernaTX, Inc." without the comma or suffix tripping us up
        first = _first_core_word(name)
        # return True as soon as any returned trial is actually led by this company
        for s in r.json().get("studies", []):
            lead = (s.get("protocolSection", {})
                     .get("sponsorCollaboratorsModule", {})
                     .get("leadSponsor", {}).get("name", ""))
            if first and first in lead.lower():
                return True
        return False
    # any error just counts as no trials
    except Exception:
        return False


def has_financials(cik):
    """True if EDGAR has an R&D expense figure for this company."""
    # try each candidate R&D tag and return True on the first one that has data
    for tag in RD_TAGS:
        try:
            r = _get(SEC_CONCEPT.format(cik=cik, tag=tag))
            if r.status_code == 200:
                return True
        except Exception:
            pass
    return False


def check_company(cik, sic, info):
    """Return a universe row if this company has BOTH trials and financials, else None."""
    ticker, name = info["ticker"], info["name"]
    # keep the company only if it has both a real pipeline and real financials
    if has_trials(name) and has_financials(cik):
        return {"ticker": ticker, "name": name, "cik": cik, "sector": SIC_LABELS[sic]}
    return None


def main():
    # nudge the user to set their own email before hitting SEC
    if "you@example.com" in SEC_USER_AGENT:
        print("!! Edit SEC_USER_AGENT to your email first.\n")

    tickers = load_ticker_file()

    # full sweep: page through every SIC, remembering the FIRST SIC each CIK
    # showed up under (that's the sector label we keep).
    cik_sic = {}
    for sic in SIC_CODES:
        print(f"Paging through SIC {sic}...")
        try:
            # record each CIK under the first SIC it appears in
            for cik in ciks_in_sic(sic):
                cik_sic.setdefault(cik, sic)
        except Exception as e:
            print(f"  error on SIC {sic}: {e}")
    print(f"\n{len(cik_sic)} unique biotech CIKs from SIC codes.")

    # only the CIKs that have a public ticker are worth checking
    candidates = [(cik, sic, tickers[cik]) for cik, sic in cik_sic.items()
                  if cik in tickers]
    print(f"{len(candidates)} have a ticker, checking trials + financials "
          f"({WORKERS} at a time)...\n")

    # the trials and financials checks are just independent network calls, so run
    # a pool of them at once instead of waiting on each one serially.
    universe = []
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        # kick off a check for every candidate at once
        futures = [pool.submit(check_company, cik, sic, info)
                   for cik, sic, info in candidates]
        # collect the results as each one finishes
        for fut in as_completed(futures):
            done += 1
            row = fut.result()
            # keep the row only if the company survived both checks
            if row:
                universe.append(row)
            # print a progress line every 50 companies
            if done % 50 == 0:
                print(f"  ...checked {done}/{len(candidates)}, kept {len(universe)}")

    # sort by ticker and write the surviving universe out to companies.json
    universe.sort(key=lambda c: c["ticker"])
    with open("companies.json", "w") as f:
        json.dump(universe, f, indent=2)
    print(f"\nDONE: {len(universe)} companies with real trials + financials.")
    print("  written to companies.json. main.py loads this.")
    print("  eyeball it and drop any obvious junk.")


if __name__ == "__main__":
    main()
