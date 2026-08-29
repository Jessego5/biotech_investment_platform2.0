"""
This script fills in the financial history for companies that only have their
latest figure stored. Run it with python backfill_financials.py.

It exists so that adding history does not mean re-running ingest.py. A full
ingest re-fetches every company's trials as well, which is the expensive half
and has nothing to do with this change; the figures come from a single
companyfacts response per company that we were already making and reading only
the newest value out of.

Replacement happens per company, inside the loop. A company that fails keeps
the rows it had rather than being emptied and left that way, and an interrupted
run leaves every company it has reached already complete.

It resumes: by default a company that already has more than one year stored is
skipped, so re-running costs only what is left.
"""

import argparse
import os
import time

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from sqlalchemy import func

from app.database import SessionLocal, init_db
from app.models import Company, Financial, FINANCIAL_METRICS
from app.data_sources import fetch_financials

# a pause between companies. one request each, so this is gentler than the
# filing crawl needs to be.
PAUSE = 0.15


def years_stored(db, ticker):
    """
    The most fiscal years any single metric has for this company.

    Counting distinct years ACROSS metrics is the wrong question and silently
    skipped 715 companies on the first run: a company whose cash is FY2025 and
    whose revenue is FY2024 has two distinct years and one figure each, which
    is exactly the state this script exists to replace.
    """
    rows = (db.query(Financial.metric, func.count(Financial.id))
              .filter(Financial.company_ticker == ticker)
              .group_by(Financial.metric).all())
    return max((n for _, n in rows), default=0)


def _rows_for(financials):
    """
    The Financial rows for one company: the annual series, plus the current
    figure when it is fresher than the last year end.

    Both are needed and they are not the same number. The series is annual so
    that years compare against years; the current figure takes the newest
    balance of any form, so Moderna's cash is the $1.7bn it reported for Q2
    2026 and not the $2.6bn it held at the 2025 year end. Storing only the
    series quietly moved every runway calculation onto stale cash.

    They are told apart by fiscal_period: the series is all "FY", so the trend
    reads only those and the current figure is whatever row is newest.
    """
    from app.models import Financial, FINANCIAL_METRICS

    history = financials.get("history") or {}
    rows = []
    for metric in FINANCIAL_METRICS:
        entries = list(history.get(metric) or [])
        latest = financials.get(metric)
        # a company whose history could not be read still gets its latest
        # figure, so this never loses what the old shape captured
        if latest and not any(e.get("period_end") == latest.get("period_end")
                              for e in entries):
            entries.append(latest)
        for e in entries:
            rows.append(Financial(
                metric=metric, value=e["value"], fiscal_year=e["fiscal_year"],
                fiscal_period=e.get("fiscal_period"),
                period_end=e.get("period_end"),
            ))
    return rows


def replace_financials(db, company, financials):
    """
    Write the whole series for one company, replacing what it had.

    Returns the number of rows written. Zero means the fetch produced nothing
    usable, and in that case the existing rows are left alone: a company that
    reports under IFRS has no us-gaap facts, and emptying its table would turn
    "we could not read this" into "this company reports nothing".
    """
    rows = _rows_for(financials)
    for row in rows:
        row.company_ticker = company.ticker
    if not rows:
        return 0

    db.query(Financial).filter(
        Financial.company_ticker == company.ticker).delete(
            synchronize_session=False)
    db.flush()
    for row in rows:
        db.add(row)
    db.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="re-read every company, not only the ones with one year")
    ap.add_argument("--tickers", metavar="LIST",
                    help="only these companies, comma separated")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()

    companies = [c for c in db.query(Company).order_by(Company.ticker).all()
                 if c.cik]
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        companies = [c for c in companies if c.ticker in wanted]
    elif not args.refresh:
        companies = [c for c in companies if years_stored(db, c.ticker) <= 1]

    if not companies:
        print("Every company already has more than one year stored.")
        db.close()
        return

    print(f"Reading financial history for {len(companies)} companies...\n")

    written = failed = empty = 0
    for n, company in enumerate(companies, 1):
        try:
            financials = fetch_financials(company.ticker, company.cik)
        except Exception as e:
            # not recorded, so the next run tries again rather than treating
            # this company as read and empty
            print(f"  [{n:>3}/{len(companies)}] {company.ticker:6} FAILED: {e}")
            failed += 1
            continue

        if not financials.get("available"):
            print(f"  [{n:>3}/{len(companies)}] {company.ticker:6} "
                  f"{financials.get('reason', 'unavailable')}")
            empty += 1
            continue

        rows = replace_financials(db, company, financials)
        if not rows:
            empty += 1
            continue
        written += rows
        years = sorted({r["fiscal_year"] for m in (financials.get("history") or {}).values()
                        for r in m if r.get("fiscal_year")})
        span = f"{years[0]}-{years[-1]}" if years else "?"
        print(f"  [{n:>3}/{len(companies)}] {company.ticker:6} "
              f"rows={rows:<4} years={span}")
        time.sleep(PAUSE)

    total = db.query(Financial).count()
    db.close()
    print(f"\nDONE. {written} rows written, {total} in the table. "
          f"{empty} companies reported nothing readable, {failed} failed and "
          f"will be retried on the next run.")


if __name__ == "__main__":
    main()
