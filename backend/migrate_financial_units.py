"""
This adds the unit column to financials, where the currency a figure was
reported in now lives.

It only adds the column. Nothing can fill it in from what is already stored: the
unit was thrown away when the SEC response was parsed, and the raw archive keeps
the resolved figures rather than the XBRL they came from, so the currency of an
existing row is genuinely not knowable here. The rows stay null, which reads as
"unknown" everywhere and never as dollars, and a dollar threshold declines to
judge them rather than guessing. To fill them in, re-read the figures from the
source with:

    python backfill_financials.py --refresh

which fetches one companyfacts response per company and writes the unit with
every value. Run this first, or the write will fail on a column that is not
there yet.

Run it with python migrate_financial_units.py, or --dry-run to say what it would
do.
"""

import argparse

from sqlalchemy import inspect, text

from app.database import engine


def existing_columns(conn):
    return {c["name"] for c in inspect(conn).get_columns("financials")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    args = ap.parse_args()

    with engine.begin() as conn:
        have = existing_columns(conn)
        rows = conn.execute(text("SELECT COUNT(*) FROM financials")).scalar()
        if "unit" in have:
            filled = conn.execute(text(
                "SELECT COUNT(*) FROM financials WHERE unit IS NOT NULL")).scalar()
            print(f"financials already has unit: {filled} of {rows} rows carry one")
            if filled < rows:
                print("  fill the rest with: python backfill_financials.py --refresh")
            return

        print(f"financials has {len(have)} columns and {rows} rows; adding unit")
        if args.dry_run:
            print("  would add unit VARCHAR, left null on every existing row")
            print("  then: python backfill_financials.py --refresh")
            return

        conn.execute(text("ALTER TABLE financials ADD COLUMN unit VARCHAR"))
        print("  added unit, null on every existing row")
        print("  now run: python backfill_financials.py --refresh")


if __name__ == "__main__":
    main()
