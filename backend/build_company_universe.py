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

# the financials check comes from the app rather than being written again here.
# it used to be a second implementation, and the two drifted: the app learned to
# read ifrs-full tags and to fetch everything a company filed in one request,
# while this file kept probing us-gaap tag by tag. That is why BioNTech and
# GlaxoSmithKline were never candidates at all, despite filing full accounts.
from app.data_sources import fetch_company_facts, RD_TAGS as APP_RD_TAGS

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

# The SIC codes a medical company files under. The labels double as the "sector"
# we store, so the frontend can filter by it.
#
# Three of these were the whole universe for a long time, which quietly excluded
# every device and diagnostics company: Boston Scientific runs 373 trials and
# Edwards Lifesciences 83, and neither files under a pharma code.
SIC_CODES = ["2836", "2834", "8731", "2835", "2833",
             "3841", "3845", "3842", "3844", "3826", "3827", "8071"]
SIC_LABELS = {
    "2836": "Biologics",
    "2834": "Pharma preparations",
    "8731": "Bio research",
    "2835": "Diagnostics",
    "2833": "Medicinal chemicals",
    "3841": "Medical devices",
    "3845": "Medical devices",
    "3842": "Medical devices",
    "3844": "Medical devices",
    "3826": "Lab instruments",
    "3827": "Lab instruments",
    "8071": "Medical labs",
}

# A SIC code is not enough on its own. A foreign company listing as an ADR gets a
# generic code whatever it does, so Shionogi (97 trials) and CSL file under
# "American Depositary Receipts", and argenx sat outside the three original codes
# entirely. Any SEC filer sponsoring at least this many phase-labelled
# interventional trials is a candidate too, whatever it files under.
#
# This cannot be the only rule either. Colgate-Palmolive runs 105 trials and 100
# of them are phased, because toothpaste efficacy is real clinical research, and
# Polaris has 20. So the two rules are a candidate pool rather than an answer,
# and why each company qualified is recorded on its row.
MIN_PHASED_TRIALS = 3

# Companies the sponsor rule lets in whose value does not depend on what the
# trials find, so a pipeline signal and a cash runway say nothing useful about
# them. Listed by name, with the reason, because this is a judgement and a
# judgement should be arguable rather than buried in a threshold.
#
# Consumer health is deliberately NOT here. Colgate runs a hundred phased trials
# and Haleon eighteen; their studies are real clinical research and their sector
# label says what they are, so a reader can filter them out. Only companies whose
# trials are incidental to the business are dropped.
NOT_A_PIPELINE = {
    "ACCENTURE": "IT consulting; its studies are client work, not a pipeline",
}

BROWSE = "https://www.sec.gov/cgi-bin/browse-edgar"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
CT_BASE = "https://clinicaltrials.gov/api/v2/studies"
HEADERS = {"User-Agent": SEC_USER_AGENT}

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


class TrialCheckFailed(Exception):
    """The trials check could not be completed, which is not the same as no trials."""


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
    # a failed request is not an answer. letting it read as "no trials" silently
    # removes a real company from a committed file, and across 781 candidates
    # that happens several times a run: IQVIA, Phathom and PMV Pharma all
    # vanished that way, each of them plainly running trials.
    except Exception as e:
        raise TrialCheckFailed(str(e)) from e


def has_financials(cik):
    """
    True if EDGAR reports an R&D expense for this company, under either
    accounting standard.

    One request for everything the company filed, rather than a request per tag
    name. Asking per tag cannot tell "this company does not report that" from "I
    guessed the wrong name", since both come back 404, and it read every foreign
    issuer as having no financials because their figures are in ifrs-full.
    """
    try:
        facts = fetch_company_facts(cik).get("facts", {})
    except Exception:
        return False
    for tag in APP_RD_TAGS:
        taxonomy, _, name = tag.rpartition(":")
        if name in facts.get(taxonomy or "us-gaap", {}):
            return True
    return False


def sponsors_from_registry(tickers, already):
    """
    Candidates the SIC sweep cannot see: SEC filers that sponsor phase-labelled
    interventional trials but file under some other code.

    Reads the registry table ingest_registry.py fills. Without it this returns
    nothing and the universe is the SIC sweep alone, which is a smaller universe
    rather than a broken one.
    """
    try:
        from app.database import SessionLocal
        from app.models import RegistryTrial
        from sqlalchemy import func
    except Exception:
        return {}

    def key(name):
        n = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper())
        n = " ".join(w for w in n.split() if w.lower() not in SUFFIXES)
        return n

    # a filer is findable by its normalised name; collisions are rare enough that
    # the first one wins and a wrong match would have to share a whole name
    by_name = {}
    for cik, info in tickers.items():
        k = key(info["name"])
        if k:
            by_name.setdefault(k, (cik, info))

    db = SessionLocal()
    try:
        rows = (db.query(RegistryTrial.sponsor, func.count(RegistryTrial.id))
                .filter(RegistryTrial.phase.isnot(None),
                        RegistryTrial.phase.like("PHASE%"))
                .group_by(RegistryTrial.sponsor).all())
    except Exception:
        return {}
    finally:
        db.close()

    phased = {}
    for sponsor, n in rows:
        hit = by_name.get(key(sponsor))
        if hit:
            phased[hit[0]] = phased.get(hit[0], 0) + n

    return {cik: n for cik, n in phased.items()
            if n >= MIN_PHASED_TRIALS and cik not in already}


def check_company(cik, sic, info):
    """
    Return a universe row if this company has BOTH trials and financials, else
    None. Raises TrialCheckFailed if the trials check could not be made, so the
    caller can keep what it already knew rather than dropping the company.
    """
    ticker, name = info["ticker"], info["name"]
    # a company whose trials are incidental to what it does
    key = re.sub(r"[^A-Z ]", " ", name.upper()).split()
    if key and key[0] in NOT_A_PIPELINE:
        return None
    # keep the company only if it has both a real pipeline and real financials
    if has_trials(name) and has_financials(cik):
        return {"ticker": ticker, "name": name, "cik": cik,
                "sector": SIC_LABELS.get(sic, "Other"),
                # why this company is here, so a reader can disagree with the
                # judgement rather than having to reverse-engineer it
                "included_because": (f"SIC {sic}" if sic in SIC_LABELS
                                     else "sponsors phase-labelled trials")}
    return None


def load_previous():
    """
    The universe from the last run, keyed by CIK.

    Sourcing replaces this file wholesale, and two things make that lossy. A
    company can drop out of SEC's ticker file while still filing perfectly good
    accounts, and a transient error during a check reads as a company having
    nothing. Either way it disappears from a committed file with no trace, so a
    company that qualified before is kept unless this run positively finds it no
    longer qualifies.
    """
    try:
        with open("companies.json") as f:
            return {r["cik"]: r for r in json.load(f) if r.get("cik")}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main():
    # nudge the user to set their own email before hitting SEC
    if "you@example.com" in SEC_USER_AGENT:
        print("!! Edit SEC_USER_AGENT to your email first.\n")

    tickers = load_ticker_file()
    previous = load_previous()
    if previous:
        print(f"{len(previous)} companies from the previous run, kept unless this "
              f"run finds they no longer qualify.\n")

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
    print(f"{len(candidates)} have a ticker.")

    # then the ones no SIC code would have found
    extra = sponsors_from_registry(tickers, {c for c, _, _ in candidates})
    if extra:
        print(f"{len(extra)} more sponsor {MIN_PHASED_TRIALS}+ phase-labelled "
              f"trials but file under another code.")
        candidates += [(cik, None, tickers[cik]) for cik in extra]
    print(f"checking trials + financials on {len(candidates)} "
          f"({WORKERS} at a time)...\n")

    # the trials and financials checks are just independent network calls, so run
    # a pool of them at once instead of waiting on each one serially.
    universe = []
    done = failed = 0
    checked_ciks = set()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        # kick off a check for every candidate at once
        futures = {pool.submit(check_company, cik, sic, info): cik
                   for cik, sic, info in candidates}
        # collect the results as each one finishes
        for fut in as_completed(futures):
            done += 1
            cik = futures[fut]
            try:
                row = fut.result()
            except TrialCheckFailed:
                # the check never completed, so this says nothing about the
                # company. fall back to whatever the last run concluded.
                failed += 1
                if cik in previous:
                    universe.append(previous[cik])
                continue
            checked_ciks.add(cik)
            # keep the row only if the company survived both checks
            if row:
                universe.append(row)
            # print a progress line every 50 companies
            if done % 50 == 0:
                print(f"  ...checked {done}/{len(candidates)}, kept {len(universe)}")

    # a company that qualified before and was not checked this time is kept. it
    # usually means it dropped out of SEC's ticker file, which is a fact about
    # the file rather than about the company: Catalyst Pharmaceuticals is listed
    # and filing, and simply is not listed there any more.
    known = {c["cik"] for c in universe if c.get("cik")}
    carried = [row for cik, row in previous.items()
               if cik not in known and cik not in checked_ciks]
    universe.extend(carried)
    if carried:
        print(f"\n  carried over {len(carried)} companies that qualified before "
              f"and were not re-checked this run")
    if failed:
        print(f"  {failed} checks could not be completed and did not count "
              f"against the company")

    # sort by ticker and write the surviving universe out to companies.json
    universe.sort(key=lambda c: c["ticker"])
    with open("companies.json", "w") as f:
        json.dump(universe, f, indent=2)
    print(f"\nDONE: {len(universe)} companies with real trials + financials.")
    print("  written to companies.json. main.py loads this.")
    print("  eyeball it and drop any obvious junk.")


if __name__ == "__main__":
    main()
