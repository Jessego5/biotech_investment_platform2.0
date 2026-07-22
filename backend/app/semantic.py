"""
This file searches the trial text by meaning, for the questions the structured
fields can't answer like mechanisms, mutations, or therapies such as CAR-T. Each
trial's text gets embedded once by embed_trials.py, and here we load those vectors
into a FAISS index, embed the query, and rank by cosine similarity.
"""

import numpy as np

from .database import SessionLocal
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
            # decode the raw bytes back into a float32 vector
            vecs.append(np.frombuffer(t.embedding, dtype=np.float32))
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


def semantic_search(query, k=8):
    """Return up to k trial dicts most similar in meaning to the query text."""
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
