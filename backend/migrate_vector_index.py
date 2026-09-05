"""
Give the vector search an index. Until now every semantic lookup read the whole
table.

334,624 passages at 1,536 dimensions is 2.2 GB of vectors, and a question
scoped to no company had to compute cosine distance against every one of them
before it could answer. That was survivable on a laptop with the whole table in
page cache and is the single largest cost of running this anywhere else: it
sets the instance size, and it sets how long a reader waits.

HNSW rather than IVFFlat. IVFFlat has to be built against data that is already
representative — build it early, or ingest another year of filings, and recall
falls away with nothing to show that it has. HNSW costs more to build and more
on disk, and is the one that keeps working while the corpus grows, which this
corpus does.

vector_cosine_ops, because search_filings orders by <=>. An index built for a
different operator is an index the planner ignores, which reads exactly like
the index not helping — so the two are written down next to each other below.

What this does NOT speed up: a search already narrowed to one company. That
filter leaves a few hundred passages, the planner scans them, and it is right
to — the index earns its place on the corpus-wide questions that had nowhere to
start from.

Safe to re-run: each index is created only if it is missing, and nothing here
drops or rewrites data.

    python migrate_vector_index.py --dry-run
    python migrate_vector_index.py
"""

import argparse
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

# The operator the search orders by, and the operator class that indexes it.
# They are written down together because they are one decision: an index built
# for a different operator is an index the planner ignores, and the symptom is
# a query that is exactly as slow as it was before, with an index on disk
# saying otherwise. test_vector_index.py holds the two to each other.
OPERATOR = "<=>"
OPS_CLASS = "vector_cosine_ops"

# Defaults for m and ef_construction, deliberately. They are pgvector's own,
# they are what the recall numbers in its README describe, and raising
# ef_construction is a build-time cost paid on every rebuild for a recall gain
# this corpus has not been measured to need. Change it with an eval, not a hunch.
INDEXES = [
    ("ix_filing_chunks_embedding_hnsw", "filing_chunks", "embedding"),
    ("ix_trials_embedding_hnsw", "trials", "embedding"),
]

# The second vector space — the passage with a line naming its filing prepended
# — is still the experiment rather than the shipping search, and indexing it
# costs the same again in build time and disk. Opt in once it wins.
CONTEXT_INDEX = ("ix_filing_chunks_embedding_ctx_hnsw", "filing_chunks", "embedding_ctx")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would be built, and what it needs, without building")
    ap.add_argument("--context", action="store_true",
                    help="also index embedding_ctx, the contextual vector space")
    # Below the size of the graph, pgvector builds in two passes and spills to
    # disk: correct, and several times slower. The graph for this corpus is
    # about 2 GB, so on anything small it spills whichever number goes here —
    # the default is chosen to leave a 4 GB machine able to answer while it
    # builds, and is worth raising on the instance that will serve.
    ap.add_argument("--build-memory", type=int, default=1024, metavar="MB",
                    help="maintenance_work_mem for the build (default 1024)")
    args = ap.parse_args()

    if engine.dialect.name != "postgresql":
        sys.exit("HNSW is a pgvector index. On SQLite the search is a Python "
                 "loop over stored bytes and there is nothing to index.")

    wanted = INDEXES + ([CONTEXT_INDEX] if args.context else [])

    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")

        for name, table, column in wanted:
            exists = conn.execute(text(
                "select 1 from pg_indexes where indexname = :n"), {"n": name}).first()
            if exists:
                size = conn.execute(text(
                    "select pg_size_pretty(pg_relation_size(cast(:n as regclass)))"),
                    {"n": name}).scalar()
                print(f"{name}: already built, {size}")
                continue

            rows = conn.execute(text(
                f"select count({column}) from {table}")).scalar()
            # a vector is dim * 4 bytes and the graph adds its neighbour lists on
            # top; near enough to warn before filling a disk, not a promise
            estimate_gb = rows * 6.4e3 / 1e9
            if args.dry_run:
                print(f"{name}: would build over {rows:,} vectors, "
                      f"roughly {estimate_gb:.1f} GB")
                continue

            mem = args.build_memory
            conn.execute(text(f"set maintenance_work_mem = '{mem}MB'"))
            print(f"building {name} over {rows:,} vectors "
                  f"(~{estimate_gb:.1f} GB, {mem} MB build memory) — this is slow")
            t0 = time.time()
            conn.execute(text(
                f"CREATE INDEX {name} ON {table} "
                f"USING hnsw ({column} {OPS_CLASS})"))
            size = conn.execute(text(
                "select pg_size_pretty(pg_relation_size(cast(:n as regclass)))"),
                {"n": name}).scalar()
            print(f"built in {time.time() - t0:.0f}s, {size}")

        if args.dry_run:
            return

        # an index that exists and is not used is the failure this file is set
        # up to avoid, so ask the planner rather than assuming
        zeros = "[" + ",".join(["0"] * 1536) + "]"
        plan = conn.execute(text(
            f"explain (format text) select id from filing_chunks "
            f"order by embedding <=> '{zeros}'::vector limit 10")).fetchall()
        used = any("ix_filing_chunks_embedding_hnsw" in str(r[0]) for r in plan)
        print("planner uses it:", "yes" if used else "NO — check the operator class")
        for r in plan:
            print("   ", r[0])


if __name__ == "__main__":
    main()
