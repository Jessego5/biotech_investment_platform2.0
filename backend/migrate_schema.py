"""
This adds the columns the models declare and the database does not have. It
exists because create_all creates missing tables and never missing columns, so a
column added to models.py after a database was built is simply absent and stays
absent, and nothing says so until a query names it: financials.unit went missing
between a dump and the code that restored it, and read as a broken site for an
hour because the health check does not touch the database and the service looked
healthy throughout. It only adds nullable columns, since a NOT NULL column needs
a value for every row that already exists and that is a decision about data
rather than about schema, so those are reported and left for a backfill script
to do properly. It does not drop or alter anything, which means a column the
database has and the models no longer declare is left alone rather than deleted.
Safe to re-run: it adds only what is missing. Run it with python
migrate_schema.py --dry-run first, then without.
"""

import argparse
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateColumn

from app.database import engine
from app.models import Base
import app.usage  # noqa: F401  registers ask_budget on the metadata


def drift():
    """
    Every declared column the database lacks, as (table, column) pairs, plus the
    tables it lacks entirely. The two are separated because create_all already
    handles the second and this script does not need to.
    """
    inspector = inspect(engine)
    have = {t: {c["name"] for c in inspector.get_columns(t)}
            for t in inspector.get_table_names()}
    columns, tables = [], []
    for table in Base.metadata.sorted_tables:
        if table.name not in have:
            tables.append(table.name)
            continue
        for column in table.columns:
            if column.name not in have[table.name]:
                columns.append((table, column))
    return columns, tables


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="say what is missing and add nothing")
    args = ap.parse_args()

    columns, tables = drift()

    if tables:
        print("tables the database does not have, which init_db creates on "
              "startup rather than this script:")
        for name in tables:
            print(f"    {name}")

    if not columns:
        print("Every column the models declare is present.")
        return

    dialect = engine.dialect
    added, refused = [], []
    for table, column in columns:
        if not column.nullable:
            refused.append(f"{table.name}.{column.name}")
            continue
        # let SQLAlchemy render the type for whichever database this is, rather
        # than writing Postgres DDL that SQLite silently reads differently
        ddl = CreateColumn(column).compile(dialect=dialect)
        statement = f"ALTER TABLE {table.name} ADD COLUMN {ddl}"
        if args.dry_run:
            print(f"    would run: {statement}")
        else:
            with engine.begin() as conn:
                conn.execute(text(statement))
            print(f"    added {table.name}.{column.name}")
        added.append(f"{table.name}.{column.name}")

    if refused:
        # a NOT NULL column needs a value for every existing row, and inventing
        # one here would write a number nobody chose into a database whose whole
        # claim is that its figures are traceable
        print("\nNOT added, because they are NOT NULL and every existing row "
              "would need a value:")
        for name in refused:
            print(f"    {name}")
        print("Add these with a backfill script that decides what the value is.")

    if added and not args.dry_run:
        print(f"\n{len(added)} column(s) added. Nothing was dropped or altered.")
    if refused:
        sys.exit(1)


if __name__ == "__main__":
    main()
