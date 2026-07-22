"""
This file embeds each trial's text so we can search it by meaning. It reads the
trial summary, gets an embedding from OpenAI, and stores the vector back on the
trial. Run it once after ingestion, and run it again if the trial text changes.
It is cheap, just a few cents for the whole universe, and it needs OPENAI_API_KEY
from backend/.env or the environment. Run it with python embed_trials.py.
"""

import os
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

EMBED_MODEL = "text-embedding-3-small"
BATCH = 100   # OpenAI lets us embed many texts per request, so batch to save calls


def main():
    # this needs an OpenAI key, so stop early if there isn't one
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY (in backend/.env) before running this.")
        return

    from openai import OpenAI
    client = OpenAI()
    db = SessionLocal()
    # resume-friendly: only embed trials that have text but no vector yet, so a
    # re-run after an interruption (like a rate limit) picks up where it left off.
    trials = (db.query(Trial)
                .filter(Trial.summary.isnot(None), Trial.summary != "",
                        Trial.embedding.is_(None))
                .all())
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
            t.embedding = np.asarray(item.embedding, dtype=np.float32).tobytes()
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
