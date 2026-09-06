"""
Add the lexical half of hybrid retrieval: a full-text index over filing passages.

The dense index is good at subject matter and bad at names. Asked what Bionano
Genomics says about its internal controls, the embedding finds passages about
internal controls — from whichever filers happen to sit closest in the vector
space — because "Bionano Genomics" is a handful of tokens in three thousand
characters of boilerplate and barely moves the vector. The retrieval eval shows
this directly: naming the company in the question does not reliably get you the
company's filing back.

A lexical index has the opposite failure. It cannot tell that "loss of
exclusivity" and "patent cliff" are the same subject, but it matches a company
name, a drug name, an NCT id or an accession exactly. Fusing the two rankings
covers both, and this corpus is unusually full of the identifiers that dense
retrieval blurs.

This is an EXPRESSION index rather than a stored tsvector column on purpose.
A generated column would rewrite all 3.6 GB of filing_chunks and roughly double
the table on disk; the expression index adds an index and leaves the table
alone. The cost is that every query has to spell the expression the same way —
to_tsvector('english', text) — or the planner will not use it.

Safe to re-run: the index is created only if it is missing, and nothing here
drops or rewrites data.

    python migrate_lexical_index.py
"""

import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from sqlalchemy import text

from app.database import engine

INDEX = "ix_filing_chunks_fts"
# the same expression the search has to use, kept in one place so the two
# cannot drift apart. an index on a different expression is an index the
# planner silently ignores, which looks exactly like the index being slow.
EXPRESSION = "to_tsvector('english', text)"


def main():
    if engine.dialect.name != "postgresql":
        sys.exit("Full-text search here is a Postgres index. On SQLite the "
                 "search falls back to dense only, so there is nothing to do.")

    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        exists = conn.execute(text(
            "select 1 from pg_indexes where indexname = :n"), {"n": INDEX}).first()
        if exists:
            print(f"{INDEX} already exists; nothing to do")
        else:
            rows = conn.execute(text("select count(*) from filing_chunks")).scalar()
            print(f"building {INDEX} over {rows:,} passages — this takes a few minutes")
            t0 = time.time()
            conn.execute(text(
                f"CREATE INDEX {INDEX} ON filing_chunks USING GIN ({EXPRESSION})"))
            print(f"built in {time.time() - t0:.0f}s")

        size = conn.execute(text(
            "select pg_size_pretty(pg_relation_size(cast(:n as regclass)))"),
            {"n": INDEX}).scalar()
        print(f"{INDEX}: {size}")

        # a plan check, because an index that exists and is not used is the
        # failure mode this whole file is set up to avoid
        plan = conn.execute(text(
            f"explain (format text) select id from filing_chunks "
            f"where {EXPRESSION} @@ plainto_tsquery('english', 'patent expiry') "
            f"limit 10")).fetchall()
        used = any(INDEX in str(r[0]) for r in plan)
        print("planner uses it:", "yes" if used else "NO — check the expression")
        for r in plan:
            print("   ", r[0])


if __name__ == "__main__":
    main()
