"""
This script fills the database with the whole biotech universe. It reads
companies.json, which build_company_universe.py produces, and for each company it
fetches the trials and financials from the live APIs and writes them into the
database. You run it once in a while so the web app can serve fast from the
database instead of hitting the APIs on every request. It is a polite batch job
with small delays between companies, meant to run every so often and not per user
request. Run it with python ingest.py.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor

from app.database import SessionLocal, init_db
from app.models import Company, Trial, Financial
from app.data_sources import fetch_trials, fetch_financials

COMPANIES_PATH = os.path.join(os.path.dirname(__file__), "companies.json")

# how many companies to fetch at once. the DB writes still happen one at a time
# on the main thread (SQLite has a single writer), only the network calls run
# in parallel.
WORKERS = 8

# the same overrides main.py uses. a couple of companies register trials under a
# different name than their SEC legal name, so we search under the working name.
SPONSOR_OVERRIDES = {
    "MRNA": "ModernaTX",
    "SDGR": "Schrödinger",
}


def load_universe():
    """companies.json rows plus the override companies (which aren't in the file)."""
    # read the filtered universe out of companies.json
    with open(COMPANIES_PATH) as f:
        rows = json.load(f)

    # key the rows by ticker so we can add to and update them
    universe = {r["ticker"]: dict(r) for r in rows}
    # make sure the override companies get ingested too, even if they're not in the file
    for ticker, name in SPONSOR_OVERRIDES.items():
        if ticker not in universe:
            universe[ticker] = {"ticker": ticker, "name": name,
                                "cik": None, "sector": None}
    # attach the override search-name wherever we have one
    for ticker in SPONSOR_OVERRIDES:
        universe[ticker]["search_name"] = SPONSOR_OVERRIDES[ticker]
    return list(universe.values())


def fetch_company(row):
    """
    Just the network part: pull trials + financials for one company. No DB here,
    so this is safe to run in a thread pool. Returns (row, trials, financials);
    on a network error, returns an error string in place of trials so one bad
    company doesn't kill the whole run.
    """
    try:
        # search ClinicalTrials.gov by the override name if there is one, else the real name
        search_name = row.get("search_name", row["name"])
        trials = fetch_trials(search_name)
        financials = fetch_financials(row["ticker"])
        return row, trials, financials
    # on any network error, hand back the error string so one bad company doesn't crash the run
    except Exception as e:
        return row, None, str(e)


def write_company(db, row, trials, financials):
    """Write one company's fetched data into the DB (main thread only)."""
    ticker = row["ticker"]

    # upsert the company row, creating it if it isn't already there
    company = db.get(Company, ticker)
    if company is None:
        company = Company(ticker=ticker)
        db.add(company)
    # refresh its top-level fields
    company.name = row["name"]
    company.sector = row.get("sector")
    company.cik = financials.get("cik") or row.get("cik")

    # wipe the old trials and financials so we write a clean snapshot
    company.trials.clear()
    company.financials.clear()
    db.flush()

    # add a Trial row for each fetched trial
    for t in trials:
        company.trials.append(Trial(
            nct_id=t["nct_id"], title=t["title"], phase=t["phase"],
            status=t["status"], lead_sponsor=t["lead_sponsor"],
            summary=t.get("summary", ""),
        ))

    # add the financial rows, but only the metrics that actually came back
    if financials.get("available"):
        for metric in ("rd_expense", "cash"):
            entry = financials.get(metric)
            if entry:
                company.financials.append(Financial(
                    metric=metric, value=entry["value"],
                    fiscal_year=entry["fiscal_year"],
                ))


def main():
    init_db()
    db = SessionLocal()
    universe = load_universe()
    print(f"Ingesting {len(universe)} companies ({WORKERS} fetches at a time)...\n")

    done = 0
    # fetch everything in parallel, but write to SQLite one at a time as results
    # come back (SQLite only allows a single writer).
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for row, trials, financials in pool.map(fetch_company, universe):
            done += 1
            # trials being None means the fetch itself failed, so skip it, don't crash
            if trials is None:
                print(f"  [{done:>3}/{len(universe)}] {row['ticker']:6} "
                      f"FETCH FAILED: {financials}")
                continue
            # write this company and commit it, rolling back if the write fails
            try:
                write_company(db, row, trials, financials)
                db.commit()
                fin_ok = financials.get("available", False)
                print(f"  [{done:>3}/{len(universe)}] {row['ticker']:6} "
                      f"trials={len(trials):>3} financials={'yes' if fin_ok else 'no'}")
            except Exception as e:
                db.rollback()
                print(f"  [{done:>3}/{len(universe)}] {row['ticker']:6} ERROR: {e}")

    db.close()
    print("\nDONE. Database populated. Start the API with: uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
