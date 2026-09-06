"""
This copies the tables that are correct and expensive to rebuild from the local
SQLite database into Postgres. Not everything should move: companies, trials and
financials are deliberately not copied, because the SQLite copy holds a universe
of 746 against the 787 now sourced and still carries the misattributions the
sponsor rule used to allow, 65 Merck KGaA trials filed under Merck & Co and 430
Nova Scotia and university studies filed under a semiconductor company, so those
are re-fetched rather than carried. What is copied is the work that would cost
hours or money to reproduce: registry_trials at 112,812 studies and about 113 API
pages, filings and filing_chunks at 71,872 chunks that were paid for once as
embeddings, and aliases at 51,400 rows from a multi-hour crawl over ten years of
Exhibit 21. Embeddings travel through the ORM rather than as raw bytes on
purpose, since SQLite stores a vector as float32 bytes and Postgres as a real
vector column and the Embedding column type converts in both directions, so
reading and writing through the models is what makes the two representations
agree. Run it with DATABASE_URL=postgresql+psycopg://... python
migrate_to_postgres.py, or --dry-run to report what would move.
"""

import argparse
import json
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import engine as target_engine
from app.models import (Base, Company, RegistryTrial, Filing, FilingChunk, Alias)

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "biotech.db")
BATCH = 1000

# in dependency order: a table that points at another has to follow it
TABLES = [
    (RegistryTrial, None),
    (Filing, "company_ticker"),
    (FilingChunk, None),          # points at filings, handled by filing ids below
    (Alias, "company_ticker"),
]


def _rows(session, model, offset, limit):
    return session.query(model).order_by(model.id).offset(offset).limit(limit).all()


def _copy_column_values(row, model):
    """Every mapped column, so primary keys and embeddings both survive."""
    return {c.name: getattr(row, c.name) for c in model.__table__.columns}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if "sqlite" in str(target_engine.url):
        raise SystemExit("DATABASE_URL is not set to Postgres; nothing to migrate into")

    source_engine = create_engine(f"sqlite:///{SQLITE_PATH}")
    Source = sessionmaker(bind=source_engine)
    Target = sessionmaker(bind=target_engine)
    Base.metadata.create_all(target_engine)

    src, dst = Source(), Target()
    try:
        # The universe is seeded first, from companies.json rather than from the
        # old database, because aliases and filings point at it and cannot be
        # written before it exists.
        #
        # This has to happen before ingestion rather than after. _leads resolves
        # a sponsor through the alias table and sponsor_names_for reads the
        # registry table, so running the fetch against an empty Postgres silently
        # strips both routes: a first attempt at this ingested 442 companies
        # before it was noticed that Eli Lilly had come back with zero trials.
        if not args.dry_run:
            seeded = 0
            existing = {t for (t,) in dst.query(Company.ticker).all()}
            with open(os.path.join(os.path.dirname(__file__), "companies.json")) as f:
                for row in json.load(f):
                    if row["ticker"] in existing:
                        continue
                    dst.add(Company(ticker=row["ticker"], cik=row.get("cik"),
                                    name=row["name"], sector=row.get("sector")))
                    seeded += 1
            dst.commit()
            print(f"seeded {seeded} companies from companies.json")

        tickers = {t for (t,) in dst.query(Company.ticker).all()}
        print(f"target holds {len(tickers)} companies\n")

        kept_filing_ids = set()
        for model, fk in TABLES:
            total = src.query(model).count()
            if args.dry_run:
                print(f"  {model.__tablename__:18} {total:7} rows in SQLite")
                continue

            dst.query(model).delete()
            dst.commit()

            moved = skipped = 0
            offset = 0
            while True:
                batch = _rows(src, model, offset, BATCH)
                if not batch:
                    break
                offset += len(batch)
                for row in batch:
                    if fk and getattr(row, fk) not in tickers:
                        skipped += 1
                        continue
                    if model is FilingChunk and row.filing_id not in kept_filing_ids:
                        skipped += 1
                        continue
                    dst.add(model(**_copy_column_values(row, model)))
                    if model is Filing:
                        kept_filing_ids.add(row.id)
                    moved += 1
                dst.commit()
            note = f", {skipped} skipped (their company is no longer in the universe)" if skipped else ""
            print(f"  {model.__tablename__:18} {moved:7} moved{note}")

        if not args.dry_run:
            # explicit primary keys were inserted, which leaves Postgres's
            # sequences behind them; the next insert would collide
            for model, _ in TABLES:
                dst.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{model.__tablename__}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {model.__tablename__}), 1))"))
            dst.commit()
            print("\nid sequences advanced past the copied rows")
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    main()
