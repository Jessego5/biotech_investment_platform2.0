"""
This file searches the trial text by meaning, for the questions the structured
fields can't answer like mechanisms, mutations, or therapies such as CAR-T. Each
trial's text gets embedded once by embed_trials.py, and here the query is embedded
the same way and ranked against them by cosine similarity.

How that ranking happens depends on the database. Postgres does it itself, since
the embeddings are a real vector column there. SQLite has no such thing, so every
stored vector is loaded into a FAISS index in memory instead, rebuilt on the first
query after each process start: about 4.7 seconds at 12,943 trials against 1
second once warm, which is fine now and is the reason the Postgres path exists.
"""

import os

import numpy as np

# load backend/.env so OPENAI_API_KEY is picked up when this module is used on its
# own, not just through the API. every other module that needs a key does this;
# without it, importing this directly works until the first query and then fails
# on missing credentials.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

from .database import SessionLocal, engine
from .models import Trial

EMBED_MODEL = "text-embedding-3-small"

# cosine floor: genuine biotech queries score about 0.49 to 0.61 against our
# trials, while off-topic ones ("time travel", "the weather") top out around
# 0.29. this cutoff keeps the real matches and drops the weak ones, so an
# irrelevant question gets an honest "no data" instead of the closest wrong trials.
MIN_SCORE = 0.40

# both of these are built once, on the first search
_index = None    # the FAISS index holding the unit-normalized trial vectors
_meta = None     # list of trial dicts, lined up row for row with the index


def _load():
    global _index, _meta
    # already loaded, so nothing to do
    if _meta is not None:
        return
    import faiss
    db = SessionLocal()
    try:
        # grab every trial that actually has an embedding stored
        rows = db.query(Trial).filter(Trial.embedding.isnot(None)).all()
        vecs, meta = [], []
        for t in rows:
            # the column type hands back a float32 array whichever database it
            # came out of, so there is nothing to decode here
            vecs.append(t.embedding)
            # keep the trial's fields alongside it, row for row with the vectors
            meta.append({
                "nct_id": t.nct_id, "title": t.title, "phase": t.phase,
                "status": t.status, "ticker": t.company_ticker,
                "summary": t.summary or "",
            })
        if vecs:
            # stack the vectors into one matrix
            m = np.vstack(vecs).astype(np.float32)
            # normalize each row so an inner product gives cosine similarity
            faiss.normalize_L2(m)
            # a flat inner-product index does an exact search, which is plenty fast
            # for a few thousand vectors and gives the same results as before
            index = faiss.IndexFlatIP(m.shape[1])
            index.add(m)
            _index = index
        _meta = meta
    finally:
        db.close()


def _embed_query(text):
    from openai import OpenAI
    import faiss
    # embed the query text with the same model used for the trials
    v = OpenAI().embeddings.create(model=EMBED_MODEL, input=[text]).data[0].embedding
    # FAISS wants a 2D float32 array, so shape it as a single row
    q = np.asarray([v], dtype=np.float32)
    # normalize it too so it lines up with the unit-length trial vectors
    faiss.normalize_L2(q)
    return q


def _search_in_database(query_vector, k):
    """
    Ask Postgres for the nearest trials, so nothing is loaded into memory here.

    pgvector's <=> gives cosine DISTANCE, where 0 is identical, and the rest of
    this file works in similarity, so it is converted on the way out and the same
    MIN_SCORE floor applies to both paths.
    """
    db = SessionLocal()
    try:
        distance = Trial.embedding.cosine_distance(list(query_vector))
        rows = (db.query(Trial, distance.label("distance"))
                  .filter(Trial.embedding.isnot(None))
                  .order_by(distance)
                  .limit(k)
                  .all())
        results = []
        for trial, dist in rows:
            score = 1.0 - float(dist)
            # drop weak matches, so an off-topic question gets an honest "no
            # data" rather than the closest wrong trials
            if score < MIN_SCORE:
                continue
            results.append({
                "nct_id": trial.nct_id, "title": trial.title,
                "phase": trial.phase, "status": trial.status,
                "ticker": trial.company_ticker, "summary": trial.summary or "",
                "score": score,
            })
        return results
    finally:
        db.close()


def _uses_pgvector():
    """Whether the database we're on can do the search itself."""
    return engine.dialect.name == "postgresql"


def semantic_search(query, k=8):
    """Return up to k trial dicts most similar in meaning to the query text."""
    # on Postgres the search is a query, so there is no index to build first
    if _uses_pgvector():
        return _search_in_database(_embed_query(query)[0], k)

    # make sure the index and metadata are loaded
    _load()
    # nothing to search against, so return an empty list
    if not _meta or _index is None:
        return []
    # embed the query into the same space as the trials
    q = _embed_query(query)
    # search the index for the k nearest trials by inner product (cosine)
    sims, idx = _index.search(q, k)
    results = []
    # sims and idx come back as 2D arrays with one row, so walk that row
    for score, i in zip(sims[0], idx[0]):
        # faiss returns -1 to pad the results when there are fewer than k
        if i < 0:
            continue
        # drop weak matches, meaning nothing that was truly relevant
        if float(score) < MIN_SCORE:
            continue
        # copy the trial's metadata and tack on its score
        m = dict(_meta[int(i)])
        m["score"] = float(score)
        results.append(m)
    return results
