"""
Embed each filing passage again, with a line saying which document it is from.

The retrieval eval shows the failure this is aimed at. Ask what Bionano Genomics
says about its internal controls and the dense search returns passages about
internal controls filed by other companies, because a stored passage carries no
trace of who filed it: "we may be unable to remediate the material weakness" is
almost the same sentence, and so almost the same vector, in every filing that
contains it. The company, the year and the section live in the filings table,
which the vector never sees.

So the vector is given them. Each passage is embedded as

    Vertex Pharmaceuticals (VRTX) · 10-K · fiscal year 2025 · intellectual property

    <the passage>

which is the cheap, deterministic half of what the literature calls contextual
retrieval. The expensive half asks a model to write a sentence situating the
passage in the argument of the document around it; that is worth trying next,
and it is a per-chunk LLM call rather than a string format, so it belongs behind
its own decision rather than inside this one.

Two properties worth keeping:

  - It writes to embedding_ctx, never to embedding. The shipping search is
    untouched until something is measured, and both spaces exist side by side so
    the comparison is a switch rather than a migration.

  - It is resumable. Only passages with a null embedding_ctx are fetched, so an
    interrupted run continues where it stopped instead of paying twice.

    python embed_contextual.py --dry-run     # what it would cost, no API calls
    python embed_contextual.py               # do it

Run order matters, and getting it wrong is not subtle. models.py declares
embedding_ctx, so once that code is deployed SQLAlchemy selects the column in
every filing_chunks query — including the ones that have nothing to do with
contextual embeddings. Against a database without the column, all of them fail
with UndefinedColumn, and the offline tests cannot warn about it because they
build their schema from the model and therefore always have it. ensure_column()
below adds it, and has to run before the new model code serves traffic.
"""

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from sqlalchemy import text

from app.database import SessionLocal, engine
from app.models import FilingChunk, Filing, Company

EMBED_MODEL = "text-embedding-3-small"

# passages per API call. The limit that bites is tokens per request, not rows:
# 128 passages of ~3,000 characters is roughly 96,000 tokens, comfortably inside
# it, and larger batches buy little once the request is this size.
BATCH = 128

# $ per million tokens for text-embedding-3-small, for the estimate only.
PRICE_PER_MTOK = 0.02

# roughly four characters to a token for English prose. Only used to print an
# estimate, so being a little wrong here costs nothing.
CHARS_PER_TOKEN = 4

# How many embedding requests to have in flight. The work is entirely waiting on
# a network call, so one at a time runs the whole corpus at about 43 passages a
# second — a little over two hours. The ceiling is the account's tokens-per-
# minute, not this number, so it stays modest and retries rather than racing.
WORKERS = 4

# Retries per batch. At this corpus size a 429 is not an exception, it is the
# steady state: the account's tokens-per-minute ceiling is the real limit and
# every worker meets it. So retries are generous and the wait between them is
# capped — doubling to 8 and 16 seconds spends far longer asleep than the limit
# window it is waiting out, which showed up as throughput falling below the
# single-threaded run.
ATTEMPTS = 8
MAX_BACKOFF = 4


def ensure_column():
    """Add embedding_ctx if it is not there. Nullable, so no table rewrite."""
    if engine.dialect.name != "postgresql":
        return
    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        conn.execute(text("alter table filing_chunks "
                          "add column if not exists embedding_ctx vector(1536)"))


def context_line(company_name, ticker, form, fiscal_year, section):
    """
    The document's identity, in the register the rest of the product uses.

    Written as prose rather than as a key-value header because it is going into
    an embedding, and the model that made those embeddings read prose.
    """
    who = f"{company_name} ({ticker})" if company_name else ticker
    year = f"fiscal year {fiscal_year}" if fiscal_year else "annual report"
    return f"{who} · {form or '10-K'} · {year} · {(section or '').replace('_', ' ')}"


def estimate(db):
    """How much is left to do, without dragging it all into memory.

    The obvious version of this — select the pending rows, then measure them —
    loads 334,624 passages of 3,000 characters, which is a gigabyte of text held
    to print two numbers. The database can count and add without handing any of
    it over.
    """
    row = db.execute(text("""
        select count(*) as n, coalesce(sum(length(text)), 0) as chars
        from filing_chunks
        where embedding is not null and embedding_ctx is null
    """)).mappings().one()
    return int(row["n"]), int(row["chars"])


def next_batch(db, after_id, size):
    """
    The next passages to embed, paged by id.

    Paging on the primary key rather than re-asking for "the null ones" each
    time: both are resumable, but this one walks the index once instead of
    hunting for nulls across 3.6 GB on every batch.
    """
    return (db.query(FilingChunk.id, FilingChunk.text, FilingChunk.section,
                     Filing.form, Filing.fiscal_year, Filing.company_ticker,
                     Company.name)
              .join(Filing, FilingChunk.filing_id == Filing.id)
              .outerjoin(Company, Company.ticker == Filing.company_ticker)
              .filter(FilingChunk.embedding.isnot(None))
              .filter(FilingChunk.embedding_ctx.is_(None))
              .filter(FilingChunk.id > after_id)
              .order_by(FilingChunk.id)
              .limit(size).all())


def embed(client, inputs):
    """One embedding request, retried on the failures that pass.

    A rate limit or a dropped connection is worth waiting out; anything still
    failing after ATTEMPTS is worth stopping for, because silently skipping a
    batch would leave holes that look exactly like passages nobody embedded yet.
    """
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return client.embeddings.create(model=EMBED_MODEL, input=inputs).data
        except Exception as e:
            if attempt == ATTEMPTS:
                raise
            # named rather than swallowed: whether the run is slow because of
            # rate limits or because of something else is the difference
            # between waiting and fixing, and a silent retry hides which.
            if attempt == 1 or type(e).__name__ != "RateLimitError":
                # every batch rate-limits at this size, so logging each one
                # buries everything else. The first is the signal; the rest
                # are the weather.
                print(f"    retry {attempt}: {type(e).__name__}: {str(e)[:90]}",
                      flush=True)
            time.sleep(min(2 ** attempt, MAX_BACKOFF))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what it would cost and stop")
    ap.add_argument("--limit", type=int, default=None,
                    help="only this many passages, for a trial run")
    ap.add_argument("--workers", type=int, default=WORKERS,
                    help="embedding requests in flight at once")
    args = ap.parse_args()

    ensure_column()
    db = SessionLocal()
    try:
        total, chars = estimate(db)
        if not total:
            print("every passage already has a contextual embedding")
            return
        if args.limit and args.limit < total:
            # scale the estimate to the slice actually being run, or a trial run
            # reports the cost of the whole corpus
            chars = int(chars * args.limit / total)
            total = args.limit

        tokens = chars / CHARS_PER_TOKEN
        print(f"{total:,} passages to embed")
        print(f"  ~{tokens/1e6:.1f}M tokens  ~${tokens/1e6*PRICE_PER_MTOK:.2f}  "
              f"{total//BATCH + 1:,} requests")
        if args.dry_run:
            sample = next_batch(db, 0, 1)
            print("\ndry run: nothing sent, nothing written")
            if sample:
                r = sample[0]
                print("sample context line:")
                print("  " + context_line(r.name, r.company_ticker, r.form,
                                          r.fiscal_year, r.section))
            return

        if not os.environ.get("OPENAI_API_KEY"):
            sys.exit("OPENAI_API_KEY is not set.")
        from openai import OpenAI
        client = OpenAI()

        done, after_id, t0 = 0, 0, time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            while done < total:
                # one read of several batches, so the database is touched once
                # per round rather than once per request in flight
                rows = next_batch(db, after_id,
                                  min(BATCH * args.workers, total - done))
                if not rows:
                    break
                batches = [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]
                payloads = [
                    [context_line(r.name, r.company_ticker, r.form,
                                  r.fiscal_year, r.section) + "\n\n" + (r.text or "")
                     for r in b]
                    for b in batches
                ]
                # only this thread touches the session; the workers do nothing
                # but wait on the network, which is the whole cost here
                results = list(pool.map(lambda p: embed(client, p), payloads))

                updates = []
                for batch, vectors in zip(batches, results):
                    updates += [{"id": r.id, "embedding_ctx": v.embedding}
                                for r, v in zip(batch, vectors)]
                db.bulk_update_mappings(FilingChunk, updates)
                db.commit()

                after_id = rows[-1].id
                done += len(rows)
                rate = done / max(time.time() - t0, 1e-9)
                print(f"  {done:,}/{total:,}  {rate:.0f}/s  "
                      f"~{(total - done) / max(rate, 1e-9) / 60:.0f} min left",
                      flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
