"""
This is the FastAPI backend for the biotech agent. It serves the companies from
a local database that ingest.py fills in, so browsing and filtering stay fast and
don't keep hitting the live APIs. There are two main routes, one to browse and
filter the whole universe, and one to get the full grounded write up for a single
company. The single company route reads the database first and falls back to a
live fetch if the ticker isn't stored yet, so the app works even before you run
ingestion.
"""

import json
import os

# load backend/.env if it's there, so you can keep OPENAI_API_KEY in a file
# instead of exporting it every terminal session. wrapped in a try/except
# so the app still runs fine without python-dotenv installed or without a .env file
# (a real shell-exported env var works either way).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .database import SessionLocal, init_db
from .models import Company
from .data_sources import (fetch_trials, summarize_pipeline, fetch_financials,
                           company_name)
from .analysis import build_assessment
from .narrative import generate_narrative
from .retrieval import trials_from_db, financials_from_db, query_companies
from .chat import answer_question

app = FastAPI(title="Biotech Agent API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # tighten this to your frontend origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# make sure the tables exist even if ingestion hasn't run yet (an empty DB is fine)
init_db()

# a few companies register trials under a name that doesn't match their SEC legal
# name, so searching the legal name finds nothing. override the search name for those.
SPONSOR_OVERRIDES = {
    "MRNA": "ModernaTX",
    "SDGR": "Schrödinger",
}

# built-in fallback names for the live path in case companies.json isn't present
FALLBACK_COMPANIES = {
    "RXRX": "Recursion Pharmaceuticals",
    "CRSP": "CRISPR Therapeutics",
    "NTLA": "Intellia Therapeutics",
    "BEAM": "Beam Therapeutics",
    "RARE": "Ultragenyx Pharmaceutical",
    "FATE": "Fate Therapeutics",
}

_COMPANIES_PATH = os.path.join(os.path.dirname(__file__), "..", "companies.json")


def load_company_names():
    """{ticker: sponsor_name} from companies.json (+ overrides) for the live path."""
    # try to read the names out of companies.json
    try:
        with open(_COMPANIES_PATH) as f:
            names = {c["ticker"]: c["name"] for c in json.load(f)}
    # if the file is missing or unreadable, fall back to the built-in names
    except (FileNotFoundError, json.JSONDecodeError):
        names = dict(FALLBACK_COMPANIES)
    # layer the sponsor overrides on top either way
    names.update(SPONSOR_OVERRIDES)
    return names


COMPANY_NAMES = load_company_names()


# - routes
@app.get("/")
def root():
    db = SessionLocal()
    # count how many companies are stored, and always close the session after
    try:
        count = db.query(Company).count()
    finally:
        db.close()
    return {"status": "ok", "companies_in_db": count,
            "hint": "run `python ingest.py` to populate the DB" if count == 0 else None}


@app.get("/companies")
def list_companies(min_rd: float = None, min_cash: float = None,
                   has_phase3: bool = None, min_active_trials: int = None,
                   sector: str = None):
    """
    Browse/filter the universe. All filters are optional and combine (AND).
      min_rd, min_cash     - minimum R&D expense / cash (raw dollars)
      has_phase3           - only companies with a Phase 3+ program
      min_active_trials    - minimum number of active trials
      sector               - exact sector label (e.g. "Biologics")
    The actual filtering lives in retrieval.query_companies, shared with the chat.
    """
    db = SessionLocal()
    try:
        # hand the filters off to the shared query and return the matches
        results = query_companies(db, min_rd=min_rd, min_cash=min_cash,
                                  has_phase3=has_phase3,
                                  min_active_trials=min_active_trials, sector=sector)
        return {"count": len(results), "companies": results}
    finally:
        db.close()


class Question(BaseModel):
    question: str


@app.post("/ask")
def ask(q: Question):
    """
    Grounded RAG chat. The question becomes a real DB query, and the LLM answers
    only from the retrieved rows (see chat.py). Complements the filter UI; it is
    NOT the front door.
    """
    # clean up the incoming question and reject it if it's empty
    question = (q.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Please ask a question.")
    db = SessionLocal()
    try:
        # run the full grounded chat flow and return its result
        return answer_question(question, db)
    finally:
        db.close()


@app.get("/company/{ticker}")
def analyze_company(ticker: str):
    """Full grounded assessment + LLM narrative. DB-first, live fallback."""
    ticker = ticker.upper()
    db = SessionLocal()
    try:
        # look for the company in the DB first
        company = db.get(Company, ticker)
        if company is not None:
            # served straight from the DB, the normal path once ingestion has run
            name = company.name
            cik = company.cik
            trials = trials_from_db(company)
            financials = financials_from_db(company)
            source = "database"
        else:
            # live fallback: resolve a name, then hit the APIs directly
            name = COMPANY_NAMES.get(ticker) or company_name(ticker)
            # give up with a 404 if we can't even find a name for the ticker
            if not name:
                raise HTTPException(status_code=404,
                                    detail=f"{ticker} not found in the DB or SEC ticker file.")
            # use the override search name if there is one for this ticker
            search_name = SPONSOR_OVERRIDES.get(ticker, name)
            try:
                trials = fetch_trials(search_name)
                financials = fetch_financials(ticker)
            # surface an upstream failure as a 502 instead of a raw crash
            except Exception as e:
                raise HTTPException(status_code=502,
                                    detail=f"Upstream data source error: {e}")
            cik = financials.get("cik")
            source = "live"
    finally:
        db.close()

    # roll the trials up into a pipeline summary and derive the grounded assessment
    pipeline = summarize_pipeline(trials)
    assessment = build_assessment(name, pipeline, financials)
    # the LLM (or template) narrates ONLY the facts above, it can't add numbers
    narrative = generate_narrative(name, assessment)

    return {
        "ticker": ticker,
        "name": name,
        "cik": cik,               # lets the frontend link figures back to EDGAR
        "source": source,
        "narrative": narrative,
        "pipeline": pipeline,
        "financials": financials,
        "assessment": assessment,
        "trials": trials[:20],
    }
