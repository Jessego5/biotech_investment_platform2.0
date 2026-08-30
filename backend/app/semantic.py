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
from .models import Trial, Filing, FilingChunk

EMBED_MODEL = "text-embedding-3-small"

# cosine floor: genuine biotech queries score about 0.49 to 0.61 against our
# trials, while off-topic ones ("time travel", "the weather") top out around
# 0.29. this cutoff keeps the real matches and drops the weak ones, so an
# irrelevant question gets an honest "no data" instead of the closest wrong trials.
MIN_SCORE = 0.40

# The same floor does not fit the filings. It was calibrated against trials,
# which are short and titled like the questions people ask; a filing passage is
# 3,000 characters of dense corporate prose and scores lower for saying the same
# thing. Measured across all 776 companies, taking each company's best chunk:
#
#   the weather forecast tomorrow   median 0.156   max 0.272
#   time travel and wormholes       median 0.212   max 0.268
#   best pizza recipe               median 0.094   max 0.201
#   patent protection               median 0.543
#   competition from biosimilars    median 0.516
#   manufacturing capacity          median 0.399
#
# 0.40 sits in the middle of the on-topic distribution, not above the off-topic
# one: it hid the intellectual property section of 168 of the 745 companies that
# have one, asked the most on-topic question there is, and would have answered
# "no filing passages matched" for half the database asked about manufacturing.
# Novo Nordisk's patent section scores 0.329 and is 10,000 characters long.
#
# 0.30 clears every off-topic maximum and keeps the honest "no data".
MIN_FILING_SCORE = 0.30

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


# - filing narrative

def _filing_hit(chunk, filing, score):
    """One matching passage, with enough context to be checkable."""
    return {
        "ticker": filing.company_ticker,
        "section": chunk.section,
        "form": filing.form,
        "filed": filing.filed,
        # which year this passage is FROM. Without it a 2021 risk factor and a
        # 2025 one are the same sentence to anyone reading the answer.
        "fiscal_year": filing.fiscal_year,
        "period_end": filing.period_end,
        "text": chunk.text,
        "score": score,
    }


def _scope_years(db, query_, year, all_years):
    """Narrow a filing query to one year, or to the newest report."""
    from sqlalchemy import and_
    if all_years:
        return query_
    if year is not None:
        return query_.filter(Filing.fiscal_year == int(year))
    newest = _newest_filing_join(db)
    return query_.join(newest, and_(Filing.company_ticker == newest.c.ticker,
                                    Filing.filed == newest.c.filed))


def _newest_filing_join(db):
    """
    A subquery selecting each company's most recently filed annual report.

    Joined on the filing date rather than the fiscal year because the year is
    only populated for filings read since the history was added, and a filter
    on a column that is NULL for most rows drops them silently.
    """
    from sqlalchemy import func
    return (db.query(Filing.company_ticker.label("ticker"),
                     func.max(Filing.filed).label("filed"))
              .group_by(Filing.company_ticker).subquery())


def search_filings(query, k=6, ticker=None, year=None, all_years=False):
    """
    Search the narrative sections of annual reports, which is where a company
    says in its own words what could go wrong. Pass a ticker to ask what one
    company says rather than searching every filing.

    Separate from the trial search rather than merged with it: a risk factor and
    a trial description answer different questions, and mixing them would let a
    trial outrank the passage that actually addresses "what are its risks".

    Searches the most recent annual report only, unless a year is named or
    all_years is set. Once several years of a filing are stored, "what does this
    company say about its risks" would otherwise return whichever year happened
    to score best — a 2021 passage and a 2025 passage read identically, and the
    answer would be about a company as it was four years ago with nothing to
    say so. Asking across years has to be a choice, not the default.
    """
    from sqlalchemy import and_
    q = _embed_query(query)[0]

    db = SessionLocal()
    try:
        if _uses_pgvector():
            distance = FilingChunk.embedding.cosine_distance(list(q))
            query_ = (db.query(FilingChunk, Filing, distance.label("d"))
                        .join(Filing, FilingChunk.filing_id == Filing.id)
                        .filter(FilingChunk.embedding.isnot(None)))
            if ticker:
                query_ = query_.filter(Filing.company_ticker == ticker)
            query_ = _scope_years(db, query_, year, all_years)
            rows = query_.order_by(distance).limit(k).all()
            hits = [_filing_hit(c, f, 1.0 - float(d)) for c, f, d in rows]
        else:
            # no vector search here, so score every stored chunk in memory. the
            # trial path builds a FAISS index because it is queried constantly;
            # this one is a plain dot product because the chunks are fewer and
            # the query is rarer.
            query_ = (db.query(FilingChunk, Filing)
                        .join(Filing, FilingChunk.filing_id == Filing.id)
                        .filter(FilingChunk.embedding.isnot(None)))
            if ticker:
                query_ = query_.filter(Filing.company_ticker == ticker)
            query_ = _scope_years(db, query_, year, all_years)
            rows = query_.all()
            if not rows:
                return []
            m = np.vstack([c.embedding for c, _ in rows]).astype(np.float32)
            # both sides unit length, so the dot product is cosine similarity
            m /= np.linalg.norm(m, axis=1, keepdims=True)
            scores = m @ (q / np.linalg.norm(q))
            order = np.argsort(-scores)[:k]
            hits = [_filing_hit(rows[i][0], rows[i][1], float(scores[i]))
                    for i in order]

        # a floor of its own, measured on this corpus, so an off-topic question
        # gets an honest "no data" rather than the least bad passage
        return [h for h in hits if h["score"] >= MIN_FILING_SCORE]
    finally:
        db.close()
