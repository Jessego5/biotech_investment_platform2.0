"""
This is the FastAPI backend for the biotech agent. It serves the companies from
a local database that ingest.py fills in, so browsing and filtering stay fast and
don't keep hitting the live APIs. There are two main routes, one to browse and
filter the whole universe, and one to get the full grounded write up for a single
company. The single company route reads the database first and falls back to a
live fetch if the ticker isn't stored yet, so the app works even before you run
ingestion.
"""

import datetime
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
from .models import (Company, Trial, RegistryTrial, ApprovedProduct, Filing)
from .data_sources import (fetch_trials_raw, parse_trials, summarize_pipeline,
                           fetch_financials, company_name)
from .analysis import build_assessment
from .narrative import generate_narrative
from .exclusivity import protection_for
from .retrieval import (trials_from_db, financials_from_db, query_companies,
                        derived_figures, upcoming_readouts)
from .chat import answer_question
from .changes import compare, compare_universe, latest_pair
from .raw_store import get_store, snapshot_coverage

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


@app.get("/stats")
def stats():
    """
    What the database actually holds, for the landing banner.

    Counted rather than written into the page, because every one of these
    numbers has changed as the universe widened, and a hardcoded figure would
    quietly become a claim the data no longer supports.
    """
    db = SessionLocal()
    try:
        today = datetime.date.today().isoformat()
        led = db.query(Trial).filter(Trial.role != "collaborator").count()
        return {
            "companies": db.query(Company).count(),
            "trials": led,
            "registry_trials": db.query(RegistryTrial).count(),
            "upcoming_readouts": db.query(Trial).filter(
                Trial.completion_date_type == "ESTIMATED",
                Trial.completion_date >= today,
                Trial.role == "lead").count(),
            "companies_with_protection": db.query(
                ApprovedProduct.company_ticker).filter(
                ApprovedProduct.company_ticker.isnot(None)).distinct().count(),
            "filings": db.query(Filing).count(),
        }
    finally:
        db.close()


@app.get("/companies")
def list_companies(min_rd: float = None, min_cash: float = None,
                   has_phase3: bool = None, min_active_trials: int = None,
                   sector: str = None, min_runway: float = None,
                   sort_by: str = None, limit: int = None):
    """
    Browse/filter the universe. All filters are optional and combine (AND).
      min_rd, min_cash     - minimum R&D expense / cash (raw dollars)
      has_phase3           - only companies with a Phase 3+ program
      min_active_trials    - minimum number of active trials
      sector               - exact sector label (e.g. "Biologics")
      min_runway           - minimum years of runway (liquidity / annual burn)
      sort_by              - rd | cash | active_trials | total_trials | runway,
                             each descending
      limit                - cap the number of companies returned
    The actual filtering lives in retrieval.query_companies, shared with the chat.
    """
    db = SessionLocal()
    try:
        # hand the filters off to the shared query and return the matches
        results = query_companies(db, min_rd=min_rd, min_cash=min_cash,
                                  has_phase3=has_phase3,
                                  min_active_trials=min_active_trials,
                                  sector=sector, min_runway=min_runway,
                                  sort_by=sort_by, limit=limit)
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
            # how many the sponsor really has, so a pipeline we only fetched part
            # of isn't shown as the whole of it
            reported_total = company.trial_count_total
            truncated = bool(company.trials_truncated)
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
                # fetch raw so the sponsor's real trial count survives parsing,
                # the same way ingestion does it
                raw_trials = fetch_trials_raw(search_name)
                trials = parse_trials(raw_trials, search_name)
                reported_total = raw_trials.get("totalCount")
                truncated = bool(raw_trials.get("truncated"))
                financials = fetch_financials(ticker)
            # surface an upstream failure as a 502 instead of a raw crash
            except Exception as e:
                raise HTTPException(status_code=502,
                                    detail=f"Upstream data source error: {e}")
            cik = financials.get("cik")
            source = "live"
    finally:
        db.close()

    # the FDA and readout views are database-only: both are joins over tables
    # ingestion fills, so a company being served live has neither yet
    protection, readouts = None, []
    if source == "database":
        db2 = SessionLocal()
        try:
            today = datetime.date.today().isoformat()
            protection = protection_for(db2, ticker, today)
            readouts = upcoming_readouts(db2, today, ticker=ticker, limit=10)
        except Exception:
            protection, readouts = None, []
        finally:
            db2.close()

    # roll the trials up into a pipeline summary and derive the grounded assessment
    pipeline = summarize_pipeline(trials)
    pipeline["total_trials_reported"] = reported_total
    pipeline["truncated"] = truncated
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
        # liquidity, burn and runway worked out here rather than in the browser,
        # so there is one implementation of those rules and not two
        "derived": derived_figures(financials),
        "assessment": assessment,
        # what protects the approved products, and when that runs out. Absent
        # for a company with nothing approved, which is most of them, and the
        # signal says so in words rather than leaving a blank to be read as "no
        # patents" — see app/exclusivity.py.
        "protection": protection,
        # trials with a readout still ahead of them, soonest first. Lead-only:
        # a readout the company does not run is not its catalyst to report.
        "readouts": readouts,
        "trials": trials[:20],
    }


@app.get("/snapshots")
def list_snapshots():
    """
    Which dated snapshots the archive holds, and how many companies each covers.
    The count is there because not every run covers the universe: repairing a few
    companies writes a date holding only those, and it is not a baseline anyone
    should compare against.
    """
    coverage = snapshot_coverage()
    return {"snapshots": [{"date": d, "companies": n} for d, n in coverage]}


@app.get("/changes")
def universe_changes(since: str = None, until: str = None):
    """
    What changed across the universe between two snapshots. With no dates it uses
    the newest snapshot and the most recent earlier one covering a comparable set
    of companies.

    Everything here is derived by comparing two archived payloads, so it needs no
    API call and says which two dates it compared.
    """
    store = get_store()
    if since and until:
        pair = (since, until)
    else:
        pair = latest_pair(store)
    # one snapshot is not an error, it just means nothing can be said yet
    if pair is None:
        return {"from": None, "to": None, "companies": [],
                "reason": "need two snapshots covering a comparable set of companies"}

    names = {t: SPONSOR_OVERRIDES.get(t, n) for t, n in COMPANY_NAMES.items()}
    return compare_universe(store, names, pair[0], pair[1])


@app.get("/company/{ticker}/changes")
def company_changes(ticker: str, since: str = None, until: str = None):
    """What changed for one company between two snapshots."""
    ticker = ticker.upper()
    store = get_store()
    pair = (since, until) if since and until else latest_pair(store)
    if pair is None:
        raise HTTPException(status_code=404,
                            detail="not enough snapshots to compare")

    name = SPONSOR_OVERRIDES.get(ticker, COMPANY_NAMES.get(ticker, ticker))
    result = compare(store, ticker, name, pair[0], pair[1])
    # absent from one of the dates, which is a different answer from no change
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"{ticker} is not in both snapshots ({pair[0]} and {pair[1]})")
    return result
