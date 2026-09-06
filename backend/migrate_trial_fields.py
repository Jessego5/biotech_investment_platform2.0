"""
This adds the trial fields that were being fetched and thrown away, and fills
them in from the registry table we already hold. It is a migration rather than a
re-ingest on purpose, because ingestion replaces a company's trial rows and would
cost a re-embed for fields that mostly need no network call at all: 83% of stored
trials already appear in registry_trials under the same NCT id, and that row
carries the conditions, the dates and the enrollment. What cannot be backfilled
is what registry_trials never stored, whether results were posted and whether the
trial was randomised or masked, and those stay null until a company is next
ingested, which is an honest gap rather than a claim that the trial lacked them.
Run it with python migrate_trial_fields.py, or --dry-run to say what it would do.
"""

import argparse

from sqlalchemy import inspect, text

from app.database import engine

# column name -> SQL type. Kept to types both SQLite and Postgres accept, since
# the app runs on either depending on DATABASE_URL.
NEW_COLUMNS = {
    "conditions": "TEXT",
    "start_date": "VARCHAR",
    "start_date_type": "VARCHAR",
    "completion_date": "VARCHAR",
    "completion_date_type": "VARCHAR",
    "enrollment": "INTEGER",
    "enrollment_type": "VARCHAR",
    "has_results": "BOOLEAN",
    "allocation": "VARCHAR",
    "masking": "VARCHAR",
}

# the ones registry_trials can answer for. The rest are not in that table.
BACKFILL = ["conditions", "start_date", "start_date_type",
            "completion_date", "completion_date_type",
            "enrollment", "enrollment_type"]


def existing_columns(conn):
    return {c["name"] for c in inspect(conn).get_columns("trials")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    args = ap.parse_args()

    with engine.begin() as conn:
        have = existing_columns(conn)
        missing = [c for c in NEW_COLUMNS if c not in have]
        print(f"trials has {len(have)} columns; {len(missing)} to add"
              + (f": {', '.join(missing)}" if missing else ""))

        if args.dry_run:
            joinable = conn.execute(text(
                "SELECT COUNT(*) FROM trials t "
                "JOIN registry_trials r ON r.nct_id = t.nct_id")).scalar()
            total = conn.execute(text("SELECT COUNT(*) FROM trials")).scalar()
            print(f"would backfill {joinable} of {total} rows "
                  f"({100 * joinable / max(total, 1):.0f}%) from registry_trials")
            return

        for name in missing:
            conn.execute(text(f"ALTER TABLE trials ADD COLUMN {name} {NEW_COLUMNS[name]}"))
            print(f"  added {name}")

        # one statement per column rather than one correlated subquery per row.
        # A trial can appear under more than one company, so this matches on the
        # NCT id and not on any single company's row.
        for name in BACKFILL:
            result = conn.execute(text(
                f"UPDATE trials SET {name} = ("
                f"  SELECT r.{name} FROM registry_trials r"
                f"  WHERE r.nct_id = trials.nct_id LIMIT 1) "
                f"WHERE {name} IS NULL"))
            print(f"  filled {name}: {result.rowcount} rows touched")

    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM trials")).scalar()
        print(f"\ncoverage over {total} trials:")
        for name in NEW_COLUMNS:
            n = conn.execute(text(
                f"SELECT COUNT(*) FROM trials WHERE {name} IS NOT NULL")).scalar()
            note = "" if name in BACKFILL else "   (awaits a re-ingest)"
            print(f"  {name:22} {n:6}  {100 * n / max(total, 1):5.1f}%{note}")


if __name__ == "__main__":
    main()
