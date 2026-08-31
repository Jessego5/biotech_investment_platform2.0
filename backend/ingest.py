"""
This script fills the database with the whole biotech universe. It reads
companies.json, which build_company_universe.py produces, and for each company it
fetches the trials and financials from the live APIs, archives what came back, and
writes the parsed rows into the database. You run it once in a while so the web app
can serve fast from the database instead of hitting the APIs on every request. It
is a polite batch job with small delays between companies, meant to run every so
often and not per user request.

It can also run as one slice of a bigger run. --shard 2 --of 8 processes only the
companies in slice 2 of 8, which is how it runs as several container tasks at once
against a rate-limited API, with each task doing a fair share and no company done
twice. With no shard arguments it does the whole universe, exactly as before.

--snapshot-only archives what the APIs returned without writing to the database.
Writing replaces a company's trial rows, which drops their embeddings, so this is
how a snapshot gets captured for history without costing a re-embed of everything.

    python ingest.py                    # the whole universe
    python ingest.py --shard 2 --of 8   # just this slice
    python ingest.py --snapshot-only    # capture history, touch nothing
"""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor

from app.database import SessionLocal, init_db
from app.models import Company, Trial, Financial, FINANCIAL_METRICS
from app.data_sources import (fetch_trials_raw, parse_trials, fetch_financials,
                              SPONSOR_OVERRIDES)
from backfill_financials import _rows_for
from app.raw_store import (get_store, raw_key, snapshot_date,
                           manifest_key, code_version)

COMPANIES_PATH = os.path.join(os.path.dirname(__file__), "companies.json")

# How many companies to fetch at once. The DB writes still happen one at a time
# on the main thread (SQLite has a single writer), only the network calls run
# in parallel.
#
# Configurable because it is a memory setting as much as a speed one. Each
# worker can hold a sponsor's whole response, up to a thousand studies, while it
# archives and parses it, so eight of them at once needs several gigabytes. That
# is fine on a laptop and is not fine in a container: the first containerised run
# was killed by the OOM reaper at company 53 of 787, in a 3.8 GB VM that was also
# running Postgres. A task definition sizes its own memory, so this has to be
# something the environment can set rather than a constant.
WORKERS = int(os.environ.get("INGEST_WORKERS", "8"))

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


def select_shard(universe, index, count):
    """
    Pick this task's slice of the universe. Every company lands in exactly one
    shard, so the slices never overlap and together they are the whole universe.

    Sorted by ticker first so the split doesn't depend on the order of
    companies.json, then dealt round-robin rather than in blocks: the list is
    alphabetical, and a contiguous block can land on a run of large-caps and
    leave one task doing most of the work.
    """
    if count is None or count <= 1:
        return universe
    if not 0 <= index < count:
        raise ValueError(f"shard {index} is not in range for {count} shards")
    ordered = sorted(universe, key=lambda r: r["ticker"])
    return [row for i, row in enumerate(ordered) if i % count == index]


def shard_from_env():
    """
    Read the shard settings a container task is given. Environment variables
    rather than arguments, because that is what a task definition overrides.
    Returns (index, count), or (0, None) when this is a whole-universe run.
    """
    count = os.environ.get("SHARD_COUNT")
    if not count:
        return 0, None
    return int(os.environ.get("SHARD_INDEX", 0)), int(count)


def fetch_company(row):
    """
    Just the network part: pull trials + financials for one company. No DB and no
    archiving here, so this is safe to run in a thread pool. Returns
    (row, raw_trials, financials); on a network error, returns None in place of
    the payload so one bad company doesn't kill the whole run.
    """
    try:
        # search ClinicalTrials.gov by the override name if there is one, else the real name
        search_name = (row.get("search_name")
                       or SPONSOR_OVERRIDES.get(row["ticker"])
                       or row["name"])
        raw_trials = fetch_trials_raw(search_name)
        # hand over the CIK the universe already recorded, so a company that has
        # since dropped out of SEC's ticker file still resolves
        financials = fetch_financials(row["ticker"], row.get("cik"))
        return row, raw_trials, financials
    # on any network error, hand back the error string so one bad company doesn't crash the run
    except Exception as e:
        return row, None, str(e)


def archive(store, date, row, raw_trials, financials):
    """
    Keep what the APIs returned, under today's date. Trials are stored exactly as
    ClinicalTrials.gov sent them, so a snapshot can be re-parsed later for a field
    this version of the code drops. Financials are stored as the resolved figures
    rather than the raw XBRL, since they are assembled from several concept
    endpoints and the resolved form is what a later comparison actually wants.
    """
    ticker = row["ticker"]
    store.put(raw_key("clinicaltrials", ticker, date), raw_trials)
    store.put(raw_key("sec", ticker, date), financials)


def write_company(db, row, trials, financials, trial_totals=None):
    """
    Write one company's fetched data into the DB (main thread only).

    trial_totals is the fetched trials payload, which carries how many trials the
    sponsor really has and whether the fetch stopped short of all of them.
    """
    trial_totals = trial_totals or {}
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
    # what the search said the sponsor really has, so a pipeline we only fetched
    # part of can be shown as partial rather than as the whole thing
    company.trial_count_total = trial_totals.get("totalCount")
    company.trials_truncated = bool(trial_totals.get("truncated"))

    # wipe the old trials and financials so we write a clean snapshot
    company.trials.clear()
    company.financials.clear()
    db.flush()

    # add a Trial row for each fetched trial
    for t in trials:
        company.trials.append(Trial(
            nct_id=t["nct_id"], title=t["title"], phase=t["phase"],
            status=t["status"], lead_sponsor=t["lead_sponsor"],
            role=t.get("role", "lead"),
            summary=t.get("summary", ""),
            conditions=t.get("conditions"),
            start_date=t.get("start_date"),
            start_date_type=t.get("start_date_type"),
            completion_date=t.get("completion_date"),
            completion_date_type=t.get("completion_date_type"),
            enrollment=t.get("enrollment"),
            enrollment_type=t.get("enrollment_type"),
            has_results=t.get("has_results"),
            allocation=t.get("allocation"),
            masking=t.get("masking"),
        ))

    # add the financial rows, but only the metrics that actually came back.
    # One row per metric per fiscal year, not one per metric: the whole series
    # already arrived in the same companyfacts response, and keeping only the
    # newest made every question about a company a question about one instant.
    # "Is the runway shortening" is not answerable from a single figure.
    if financials.get("available"):
        for row in _rows_for(financials):
            company.financials.append(row)


def parse_args():
    parser = argparse.ArgumentParser(description="Ingest the biotech universe.")
    parser.add_argument("--shard", type=int, default=None,
                        help="which slice of the universe this run handles")
    parser.add_argument("--of", type=int, default=None, dest="shard_count",
                        help="how many slices the universe is split into")
    parser.add_argument("--tickers", metavar="LIST",
                        help="re-ingest only these companies, comma separated. "
                             "A matching-rule change affects a handful of "
                             "companies and re-fetching all 787 to reach them "
                             "costs an hour and a snapshot nobody asked for.")
    parser.add_argument("--snapshot-only", action="store_true",
                        help="archive what the APIs return without writing to the "
                             "database, so history can be captured without "
                             "disturbing what the app is serving")
    return parser.parse_args()


def main():
    args = parse_args()
    # arguments win when given, otherwise fall back to the container's environment
    if args.shard_count:
        shard_index, shard_count = args.shard or 0, args.shard_count
    else:
        shard_index, shard_count = shard_from_env()

    init_db()
    db = SessionLocal()
    store = get_store()
    date = snapshot_date()

    universe = select_shard(load_universe(), shard_index, shard_count)
    full_run = not (args.tickers or shard_count)
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        universe = [r for r in universe if r["ticker"] in wanted]
        missing = wanted - {r["ticker"] for r in universe}
        if missing:
            # named and not in the universe file is worth saying out loud, since
            # the alternative is a run that quietly does less than was asked
            print(f"Not in companies.json, skipped: {', '.join(sorted(missing))}")
    where = (f"{len(universe)} named" if args.tickers else
             f"shard {shard_index} of {shard_count}" if shard_count else
             "full universe")
    print(f"Ingesting {len(universe)} companies ({where}, "
          f"{WORKERS} fetches at a time, snapshot {date})...\n")

    # Recorded before the run rather than after, so an interrupted run still
    # says what it was and what produced it. A partial snapshot is legitimate —
    # a targeted re-ingest archives only what it touched — but a comparison has
    # to know that it is partial rather than read 739 absent companies as 739
    # companies that disappeared.
    store.put(manifest_key(date), {
        "date": date,
        "code_version": code_version(),
        "companies_expected": len(universe),
        "full_run": full_run,
        "tickers": sorted(r["ticker"] for r in universe) if not full_run else None,
    })

    done = 0
    # fetch everything in parallel, but archive and write one at a time as results
    # come back (SQLite only allows a single writer).
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for row, raw_trials, financials in pool.map(fetch_company, universe):
            done += 1
            # a None payload means the fetch itself failed, so skip it, don't crash
            if raw_trials is None:
                print(f"  [{done:>3}/{len(universe)}] {row['ticker']:6} "
                      f"FETCH FAILED: {financials}")
                continue

            # archive before parsing. the snapshot is the durable artifact, and it
            # should survive even if today's parsing or schema turns out to be wrong.
            try:
                archive(store, date, row, raw_trials, financials)
            except Exception as e:
                print(f"  [{done:>3}/{len(universe)}] {row['ticker']:6} "
                      f"ARCHIVE FAILED: {e}")

            # archiving is the whole job in snapshot-only mode. this exists
            # because writing replaces a company's trial rows, which drops their
            # embeddings, and capturing history should not cost a re-embed.
            if args.snapshot_only:
                print(f"  [{done:>3}/{len(universe)}] {row['ticker']:6} archived")
                continue

            # write this company and commit it, rolling back if the write fails
            try:
                trials = parse_trials(raw_trials, row.get("search_name", row["name"]))
                write_company(db, row, trials, financials, raw_trials)
                db.commit()
                fin_ok = financials.get("available", False)
                print(f"  [{done:>3}/{len(universe)}] {row['ticker']:6} "
                      f"trials={len(trials):>3} financials={'yes' if fin_ok else 'no'}")
            except Exception as e:
                db.rollback()
                print(f"  [{done:>3}/{len(universe)}] {row['ticker']:6} ERROR: {e}")

    db.close()
    if args.snapshot_only:
        print(f"\nDONE. Snapshots written for {date}. The database was not touched.")
    else:
        print("\nDONE. Database populated. Start the API with: uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
