"""
This builds the company list instead of anyone typing one by hand. It used to
start from a dozen SIC codes and keep whatever they returned, which drew the
universe's edge with a list of filing codes and not where the edge actually is:
Alcon files under 3851, "Ophthalmic Goods", and runs 579 studies, so no length
of code list was going to reach it without also reaching whatever else 3851
contains. The candidate pool is now every SEC filer with a ticker, about eight
thousand, and the two questions asked of each are the ones that matter, whether
it leads clinical trials and whether it files real financials. SIC is still
fetched, but it labels the sector and corroborates a doubtful name rather than
deciding membership. Run it with python build_company_universe.py, and set
SEC_USER_AGENT to your own email first.
"""

import os
import requests
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# the financials check and the name handling both come from the app rather than
# being written again here. They used to be second implementations and the two
# drifted: the app learned to read ifrs-full tags and to fetch everything a
# company filed in one request, while this file kept probing us-gaap tag by tag.
# That is why BioNTech and GlaxoSmithKline were never candidates at all, despite
# filing full accounts.
from app.data_sources import (fetch_company_facts, RD_TAGS as APP_RD_TAGS,
                              _search_term,
                              # the naming rules sit with _core_name and _fold
                              # rather than here. The ingestion path needs the
                              # same comparison, and it cannot import upward
                              # from app/ into this script to get it.
                              _norm, _squashed, identity, parent_named_in)

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

# SIC codes that say "this is a medical company". These no longer decide who is
# in the universe; they label the sector, and they corroborate a name match that
# is close but not exact. 3851 is here because Alcon is, and 8000-series codes
# because a hospital operator running trials is a real sponsor.
MEDICAL_SIC = {
    "2833": "Medicinal chemicals",
    "2834": "Pharma preparations",
    "2835": "Diagnostics",
    "2836": "Biologics",
    "3821": "Lab instruments",
    "3826": "Lab instruments",
    "3827": "Lab instruments",
    "3841": "Medical devices",
    "3842": "Medical devices",
    "3843": "Medical devices",
    "3844": "Medical devices",
    "3845": "Medical devices",
    "3851": "Medical devices",
    "5047": "Medical distribution",
    "5122": "Medical distribution",
    "8000": "Health services",
    "8011": "Health services",
    "8050": "Health services",
    "8051": "Health services",
    "8060": "Health services",
    "8062": "Health services",
    "8071": "Medical labs",
    "8090": "Health services",
    "8093": "Health services",
    "8731": "Bio research",
}

# Companies the trials rule lets in whose value does not depend on what those
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

# Spellings no string rule reaches, because the company registers its trials
# under a name that is not a variation of its filing name at all. Keyed by CIK,
# which is the stable identifier: a ticker moves and a name changes.
#
# This is a seed, and deliberately small. Every entry is a judgement that two
# names are one company, which is the same judgement the FDA and patent joins
# will need in bulk for applicants and assignees, so it should grow into a table
# with a source column rather than stay a literal here.
ALIASES = {
    "0001682852": ["ModernaTX"],                     # Moderna, Inc.
    "0001080014": ["Innoviva Specialty Therapeutics"],  # Innoviva, Inc.
    "0000920148": ["Labcorp Corporation of America Holdings"],  # LABCORP HOLDINGS
    "0001869105": ["TheRas"],                        # BridgeBio Oncology Therapeutics
}

SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
CT_BASE = "https://clinicaltrials.gov/api/v2/studies"
HEADERS = {"User-Agent": SEC_USER_AGENT}


def _get(url, params=None, attempts=4):
    """
    GET, retrying while the failure looks temporary.

    Throttling is the expected one, but a read timeout is just as temporary and
    used to propagate, which silently removed real companies from a committed
    file.
    """
    last = None
    for attempt in range(attempts):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
            continue
        # a 403 or 429 means we got throttled, so wait and try again
        if r.status_code in (403, 429) and attempt < attempts - 1:
            time.sleep(1.5 * (attempt + 1))
            continue
        return r
    raise last


_ticker_file = None
def load_ticker_file():
    """CIK -> {ticker, name} from SEC's ticker file (loaded once)."""
    global _ticker_file
    if _ticker_file is None:
        r = _get(SEC_TICKERS)
        r.raise_for_status()
        _ticker_file = {
            f"{int(v['cik_str']):010d}": {"ticker": v["ticker"].upper(),
                                          "name": v["title"]}
            for v in r.json().values()
        }
    return _ticker_file


class TrialCheckFailed(Exception):
    """The trials check could not be completed, which is not the same as no trials."""


def fetch_sic(cik):
    """
    (sic, description) for a filer, from the submissions endpoint.

    The SIC sweep this replaced could only report codes it had already decided to
    ask for. Asking per company instead means a filer outside every code on the
    list still arrives labelled, which is how Alcon comes back "Ophthalmic Goods"
    rather than "Other".
    """
    try:
        r = _get(SEC_SUBMISSIONS.format(cik=cik))
        if r.status_code != 200:
            return None, None
        payload = r.json()
        return (payload.get("sic") or None), (payload.get("sicDescription") or None)
    except Exception:
        return None, None




_registry_index = None
def registry_index():
    """
    Registry sponsor names grouped by their first folded word, or {} when the
    registry table has not been ingested.

    Grouping matters: this is asked once per filer and there are fourteen
    thousand distinct sponsors, so comparing every pair is a hundred million
    comparisons for an answer that only ever shares a first word.
    """
    global _registry_index
    if _registry_index is None:
        index, squashed = {}, {}
        try:
            from app.database import SessionLocal
            from app.models import RegistryTrial
            db = SessionLocal()
            try:
                names = {n for (n,) in db.query(RegistryTrial.sponsor)
                         .filter(RegistryTrial.sponsor.isnot(None)).distinct()}
            finally:
                db.close()
        except Exception:
            names = set()
        for name in names:
            folded = _norm(name)
            if folded:
                index.setdefault(folded.split()[0], []).append(name)
            # a sponsor that names its parent is filed under the parent's
            # leading word too, since that is the word a filer will look up
            named = parent_named_in(name)
            if named and _norm(named):
                index.setdefault(_norm(named).split()[0], []).append(name)
            # a second index on the whole name with its gaps removed. The first
            # index cannot serve the squashed comparison: "Bristol-Myers Squibb"
            # reduces to a leading word of "bristolmyers" while the filing name
            # leads with "bristol", so the two never meet in the same bucket
            key = _squashed(name)
            if key:
                squashed.setdefault(key, name)
        _registry_index = index, squashed
    return _registry_index


def registry_identity(filing_name):
    """
    (sponsor name, confidence) from the registry we already hold, or None.

    Free, and it matches names the API's sponsor search cannot: that search wants
    whole terms, so "Moderna" returns one study led by Vertex while "ModernaTX"
    returns 140.
    """
    by_first, by_squash = registry_index()
    key = _squashed(filing_name)
    if key and key in by_squash:
        return by_squash[key], "exact"
    mine = _norm(filing_name).split()
    if not mine:
        return None
    best = None
    for candidate in by_first.get(mine[0], ()):
        how = identity(filing_name, candidate)
        if how == "exact":
            return candidate, "exact"
        if how == "near" and best is None:
            best = (candidate, "near")
    return best


def alias_identity(cik):
    """
    (sponsor name, "exact") for a spelling recorded by hand, or None.

    Asked only after the registry has failed on the filing name, so an alias
    never overrides a match the rules could make for themselves.
    """
    by_first, _ = registry_index()
    for alias in ALIASES.get(cik, ()):
        mine = _norm(alias)
        if not mine:
            continue
        for candidate in by_first.get(mine.split()[0], ()):
            if identity(alias, candidate, authoritative=True):
                return candidate, "exact"
    return None


def alias_api_identity(cik):
    """The same recorded spellings, asked of the API when the registry is silent."""
    for alias in ALIASES.get(cik, ()):
        try:
            found = api_identity(alias, authoritative=True)
        except TrialCheckFailed:
            continue
        if found:
            return found
    return None


def api_identity(filing_name, authoritative=False):
    """
    (lead sponsor, confidence) from ClinicalTrials.gov, or None.

    Only asked when the registry has nothing to say, which is the case for a
    sponsor whose studies are observational or device work: registry_trials holds
    industry-sponsored interventional studies alone, so 115 companies already in
    the universe have no row in it at all.
    """
    try:
        r = _get(CT_BASE, {"query.spons": _search_term(filing_name), "pageSize": 20})
        r.raise_for_status()
        best = None
        for s in r.json().get("studies", []):
            lead = (s.get("protocolSection", {})
                     .get("sponsorCollaboratorsModule", {})
                     .get("leadSponsor", {}).get("name", ""))
            how = identity(filing_name, lead, authoritative)
            if how == "exact":
                return lead, "exact"
            if how == "near" and best is None:
                best = (lead, "near")
        return best
    # a failed request is not an answer. Letting it read as "no trials" silently
    # removes a real company from a committed file, and across thousands of
    # candidates that happens several times a run.
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


def check_company(cik, info):
    """
    A universe row if this company leads trials and files real financials, else
    None. Raises TrialCheckFailed if the trials check could not be made, so the
    caller can keep what it already knew rather than dropping the company.

    An exact name identity stands on its own. A near one needs a medical SIC
    behind it, because "Asana, Inc." and "Asana BioSciences" are the same shape
    as "Alcon Inc" and "Alcon Research", and nothing about the trials themselves
    separates them: Asana BioSciences' studies are phase-labelled too. What
    separates them is that one of the two filers makes project-management
    software.

    An exact match is deliberately allowed through without that corroboration,
    since requiring it would throw away the foreign issuers the sweep already
    could not see: an ADR gets a generic filing code whatever the company does,
    which is why Shionogi and CSL file under "American Depositary Receipts".
    """
    name = info["name"]
    # a company whose trials are incidental to what it does
    first = re.sub(r"[^A-Z ]", " ", name.upper()).split()
    if first and first[0] in NOT_A_PIPELINE:
        return None

    # the registry answers for free and matches names the API cannot
    found = registry_identity(name)
    source = "registry"
    if not found:
        found = alias_identity(cik)
        source = "registry via a recorded alias"
    if not found:
        found = api_identity(name)
        source = "ClinicalTrials.gov"
    if not found:
        found = alias_api_identity(cik)
        source = "ClinicalTrials.gov via a recorded alias"
    if not found:
        return None
    sponsor, how = found

    sic, sic_desc = fetch_sic(cik)
    if how == "near" and sic not in MEDICAL_SIC:
        return None
    if not has_financials(cik):
        return None

    return {
        "ticker": info["ticker"], "name": name, "cik": cik,
        "sector": MEDICAL_SIC.get(sic) or sic_desc or "Other",
        "sic": sic,
        # why this company is here, and under what spelling, so a reader can
        # disagree with the judgement rather than reverse-engineer it
        "included_because": (f"{how} name match to {sponsor!r} in {source}"
                             + ("" if how == "exact" else f", SIC {sic}")),
    }


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
              f"run finds they no longer qualify.")
    known = len(registry_index()[0])
    print(f"registry holds sponsors under {known} distinct leading words"
          if known else "registry not ingested; every filer falls back to the API")
    print(f"\nchecking trials + financials on all {len(tickers)} SEC filers with a "
          f"ticker ({WORKERS} at a time)...\n")

    universe = []
    done = failed = 0
    checked_ciks = set()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(check_company, cik, info): cik
                   for cik, info in tickers.items()}
        for fut in as_completed(futures):
            done += 1
            cik = futures[fut]
            try:
                row = fut.result()
            except TrialCheckFailed:
                # the check never completed, so this says nothing about the
                # company. Fall back to whatever the last run concluded.
                failed += 1
                if cik in previous:
                    universe.append(previous[cik])
                continue
            checked_ciks.add(cik)
            if row:
                universe.append(row)
            if done % 250 == 0:
                print(f"  ...checked {done}/{len(tickers)}, kept {len(universe)}")

    # a company that qualified before and was not checked this time is kept. It
    # usually means it dropped out of SEC's ticker file, which is a fact about
    # the file rather than about the company: Catalyst Pharmaceuticals is listed
    # and filing, and simply is not listed there any more.
    have = {c["cik"] for c in universe if c.get("cik")}
    carried = [row for cik, row in previous.items()
               if cik not in have and cik not in checked_ciks]
    universe.extend(carried)
    if carried:
        print(f"\n  carried over {len(carried)} companies that qualified before "
              f"and were not re-checked this run")
    if failed:
        print(f"  {failed} checks could not be completed and did not count "
              f"against the company")

    universe.sort(key=lambda c: c["ticker"])
    with open("companies.json", "w") as f:
        json.dump(universe, f, indent=2)

    exact = sum(1 for c in universe if str(c.get("included_because", "")).startswith("exact"))
    print(f"\nDONE: {len(universe)} companies with real trials + financials.")
    print(f"  {exact} on an exact name match, {len(universe) - exact} on a near "
          f"match corroborated by a medical SIC or carried over.")
    print("  written to companies.json. main.py loads this.")


if __name__ == "__main__":
    main()
