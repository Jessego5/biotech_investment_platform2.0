"""
This embeds each trial's text so the trials can be searched by meaning. It reads
the trial summary, gets an embedding from OpenAI and stores the vector back on
the trial, and it is cheap, a few cents for the whole universe. It takes the same
slice arguments ingest.py does, so a scheduled run embeds what its own shard
just wrote rather than every shard racing for the same rows, and it only touches
trials that have text and no vector yet, which is what makes an interrupted run
safe to repeat. Run it after ingestion, and again if the trial text changes, with
python embed_trials.py or python embed_trials.py --shard 2 --of 8 for one slice.
It needs OPENAI_API_KEY from backend/.env or the environment, and exits non-zero
if there is work to do and no key.
"""

import argparse
import os
import sys
import time

import numpy as np

# load backend/.env so the key is picked up the same way the API does
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from app.database import SessionLocal
from app.models import Trial
from ingest import load_universe, select_shard, shard_from_env

EMBED_MODEL = "text-embedding-3-small"
BATCH = 100   # OpenAI lets us embed many texts per request, so batch to save calls


def pending(db, shard_index=None, shard_count=None):
    """
    Trials with text and no vector, optionally only this task's slice.

    Resume-friendly, and the reason it can be: a re-run after an interruption
    picks up exactly what is still missing rather than starting again.
    """
    q = db.query(Trial).filter(Trial.summary.isnot(None), Trial.summary != "",
                               Trial.embedding.is_(None))
    if shard_count:
        # the same split ingest.py uses, so a shard embeds what it wrote
        tickers = [row["ticker"] for row in
                   select_shard(load_universe(), shard_index or 0, shard_count)]
        q = q.filter(Trial.company_ticker.in_(tickers))
    return q.all()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=int, default=None,
                        help="which slice of the universe this task embeds")
    parser.add_argument("--of", type=int, default=None, dest="shard_count",
                        help="how many slices there are")
    args = parser.parse_args()
    if args.shard_count:
        shard_index, shard_count = args.shard or 0, args.shard_count
    else:
        shard_index, shard_count = shard_from_env()

    db = SessionLocal()
    trials = pending(db, shard_index, shard_count)

    if not trials:
        print("Nothing to embed: every trial with text already has a vector.")
        return

    # Loudly, not quietly. This used to print a note and return 0, which in a
    # scheduled task is indistinguishable from success — the run goes green and
    # the trials it just wrote have no vectors, so trial search returns nothing
    # and refuses without saying why.
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit(f"{len(trials)} trials need embedding and OPENAI_API_KEY is "
                 f"not set. Nothing was written.")

    from openai import OpenAI
    client = OpenAI()
    print(f"Embedding {len(trials)} trials that still need it ({EMBED_MODEL})...")

    def embed(texts):
        # retry a few times on OpenAI's tokens-per-minute rate limit (429)
        for attempt in range(6):
            try:
                return client.embeddings.create(model=EMBED_MODEL, input=texts)
            except Exception as e:
                # if it was a rate limit, wait a bit longer each attempt and retry
                if "rate_limit" in str(e).lower() or "429" in str(e):
                    time.sleep(4 * (attempt + 1))
                    continue
                # any other error is real, so let it propagate
                raise
        # give up once we've exhausted the retries
        raise RuntimeError("embedding still rate-limited after retries")

    done = 0
    # work through the trials one batch at a time
    for i in range(0, len(trials), BATCH):
        chunk = trials[i:i + BATCH]
        # embed the whole chunk's summaries in one call
        resp = embed([t.summary for t in chunk])
        # store each returned vector back on its trial as raw float32 bytes
        for t, item in zip(chunk, resp.data):
            # hand over the numbers; the column type stores them as a pgvector
            # column on Postgres and as raw float32 bytes on SQLite
            t.embedding = np.asarray(item.embedding, dtype=np.float32)
        # commit after each batch so progress isn't lost on an interruption
        db.commit()
        done += len(chunk)
        print(f"  {done}/{len(trials)}")
        # pause to stay under the tokens-per-minute limit
        time.sleep(1.5)

    db.close()
    print("DONE! Restart the API and the semantic chat is ready:)")


if __name__ == "__main__":
    main()
