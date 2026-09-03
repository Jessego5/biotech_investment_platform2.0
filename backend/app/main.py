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
import hmac
import re
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

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .database import SessionLocal, init_db
from .models import (Company, Trial, RegistryTrial, ApprovedProduct,
                     Filing, FilingChunk)
from .data_sources import (fetch_trials_raw, parse_trials, summarize_pipeline,
                           fetch_financials, company_name, SPONSOR_OVERRIDES)
from .analysis import build_assessment
from .narrative import generate_narrative
from .exclusivity import protection_for
from .retrieval import (trials_from_db, financials_from_db, history_from_db,
                        query_companies, derived_figures, upcoming_readouts)
from .filings import filing_url
from .chat import answer_question
from .changes import (compare, compare_universe, latest_pair,
                      snapshot_provenance)
from .raw_store import get_store, snapshot_coverage

app = FastAPI(title="Biotech Agent API", version="0.3.0")


# The only endpoint that spends money. Everything else reads the database and
# costs a query; /ask calls the model up to MAX_ROUNDS times per question, so
# an open one on a public URL is an open wallet.
#
# The key is optional on purpose: unset, the API behaves exactly as it did, so
# a local run and the test suite need no configuration. Set, it is required,
# and the frontend is the only thing that holds it.
API_KEY = os.environ.get("READBASE_API_KEY") or ""


def require_key(x_readbase_key: str = Header(default="")):
    if not API_KEY:
        return
    # compare in constant time: a plain == leaks the key a character at a time
    # to anyone willing to measure
    if not hmac.compare_digest(x_readbase_key, API_KEY):
        raise HTTPException(
            status_code=401,
            detail="This endpoint needs a key. The read-only endpoints do not.",
        )

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
# defined in data_sources so the ingest can use the same list

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


@app.get("/watchlist")
def watchlist(tickers: str = ""):
    """
    A compact row per watched company: the things that actually change.

    Deliberately not stored here. There is no user concept in this app, so a
    server-side watchlist would be one global list shared by everyone who opened
    the page. It lives in the browser, and this endpoint only answers for the
    tickers it is handed.

    What it returns is what a watcher is watching FOR: the next readout, the
    nearest loss of protection, and how long the money lasts. Not a price, and
    not a position — those would be the first figures here that are neither
    computed from a filing nor traceable to one.
    """
    wanted = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not wanted:
        return {"companies": []}

    db = SessionLocal()
    try:
        today = datetime.date.today().isoformat()
        rows = []
        for c in db.query(Company).filter(Company.ticker.in_(wanted[:50])).all():
            readouts = upcoming_readouts(db, today, ticker=c.ticker, limit=1)
            protection = protection_for(db, c.ticker, today)
            fins = financials_from_db(c)
            derived = derived_figures(fins)
            rows.append({
                "ticker": c.ticker,
                "name": c.name,
                "sector": c.sector,
                "next_readout": readouts[0] if readouts else None,
                "protection_state": protection["state"],
                "next_expiry": protection.get("next_expiry"),
                "runway": derived.get("runway"),
                "burn_source": derived.get("burn_source"),
                # a null runway means two different things and the row has to
                # be able to say which: a company funding itself has none to
                # report, which is not the same as one we could not work out
                "cash_generative": derived.get("cash_generative"),
                "liquidity_note": derived.get("liquidity_note"),
            })
        # returned in the order asked for, so the page does not reorder a list
        # the reader arranged
        order = {t: i for i, t in enumerate(wanted)}
        rows.sort(key=lambda r: order.get(r["ticker"], 999))
        return {"companies": rows}
    finally:
        db.close()


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
            # two counts, because they answer different questions: how many
            # studies we hold, and how many of them a company is running rather
            # than collaborating on. A banner describing the corpus wants the
            # first; a company's own pipeline wants the second.
            "trials": led,
            "trials_total": db.query(Trial).count(),
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
                   sort_by: str = None, limit: int = None, q: str = None):
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
      q                    - match a ticker or name, for picking a company by
                             typing rather than by knowing its ticker already
    The actual filtering lives in retrieval.query_companies, shared with the chat.

    `q` is applied here rather than in that shared query on purpose: it is a
    convenience for choosing a company, not a way of selecting a population,
    and the grounded answers must keep meaning exactly what they mean now.
    """
    db = SessionLocal()
    try:
        # hand the filters off to the shared query and return the matches
        # the limit has to come after the search, not before it. Applied first
        # it caps the population and then looks inside the cap, so a company
        # outside the first N is reported as not existing.
        results = query_companies(db, min_rd=min_rd, min_cash=min_cash,
                                  has_phase3=has_phase3,
                                  min_active_trials=min_active_trials,
                                  sector=sector, min_runway=min_runway,
                                  sort_by=sort_by,
                                  limit=None if q else limit)
        if q:
            needle = q.strip().casefold()
            results = [r for r in results
                       if needle in (r.get("ticker") or "").casefold()
                       or needle in (r.get("name") or "").casefold()]
            if limit:
                results = results[:limit]
        return {"count": len(results), "companies": results}
    finally:
        db.close()


class Question(BaseModel):
    question: str


@app.post("/ask", dependencies=[Depends(require_key)])
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


# arms that are not a candidate: a control tells you how the trial was designed,
# not what the company is developing.
# A control arm is often named after the drug it stands in for — "VX-661 Plus
# Ivacaftor Combination Placebo" — so the word is looked for anywhere in the
# name rather than only at the front, where an earlier version of this missed
# it and counted the placebo as a candidate.
_CONTROL = re.compile(
    r"\b(placebos?|shams?)\b|"
    r"^(saline|normal saline|vehicle|standard of care|best supportive care|"
    r"no intervention|observation|usual care|control)\b", re.I)

_PHASE_RANK = {"PHASE4": 4, "PHASE3": 3, "PHASE2": 2, "PHASE1": 1}


def _furthest_phase(phase):
    """The most advanced phase named in a registry phase string."""
    best, label = 0, None
    for part in (phase or "").upper().replace(" ", "").split(","):
        rank = _PHASE_RANK.get(part, 0)
        if rank > best:
            best, label = rank, part
    return best, label


def _alias_edges(trials):
    """
    Pairs of names the registry says are the same thing.

    An `otherNames` entry is often several aliases in one string — "VX-770, IVA"
    — so it is split on commas here rather than at write time, where splitting
    would have destroyed what the sponsor actually filed. A name containing a
    comma is split wrongly by this, which is the cost of reading a field that
    was filled in by hand.
    """
    for t in trials:
        if not t.intervention_aliases:
            continue
        try:
            stated = json.loads(t.intervention_aliases)
        except (ValueError, TypeError):
            continue
        for name, others in (stated or {}).items():
            for other in (others or []):
                for part in str(other).split(","):
                    part = part.strip()
                    if part:
                        yield name.strip().casefold(), part.casefold()


def studied_interventions(db, ticker):
    """
    What this company's trials are testing, with names the registry itself
    states are the same thing merged into one row.

    A candidate is filed under a code and a generic name — ivacaftor appears as
    "IVA", "Ivacaftor" and "VX-770" — and counting the strings counts one drug
    three times. ClinicalTrials.gov records the equivalence in `otherNames`, so
    the merge is the registry's claim rather than ours; where it says nothing,
    nothing is merged, and two rows for one drug is the honest outcome.

    Every merge is reported in `also_known_as`, because a row that quietly
    absorbed three names is a figure the reader cannot check.

    Lead-sponsored trials only: a study the company collaborates on is real
    involvement at a different level of control, and counting it here would
    overstate what the company is developing.
    """
    trials = (db.query(Trial)
                .filter(Trial.company_ticker == ticker,
                        Trial.role == "lead",
                        Trial.interventions.isnot(None)).all())

    # union-find over the names, joined only where the registry joins them
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a, b in _alias_edges(trials):
        union(a, b)

    marketed = {}
    for p in db.query(ApprovedProduct).filter(
            ApprovedProduct.company_ticker == ticker).all():
        for part in (p.ingredient or "").replace(";", ",").split(","):
            key = part.strip().casefold()
            if key and p.trade_name:
                marketed.setdefault(key, p.trade_name)

    groups = {}
    for t in trials:
        seen_here = set()
        for raw in (t.interventions or "").split(";"):
            name = raw.strip()
            if not name or _CONTROL.search(name):
                continue
            key = find(name.casefold())
            entry = groups.setdefault(key, {
                "trials": 0, "phase": None, "phase_rank": 0, "lead_nct": None,
                "conditions": set(), "names": {},
            })
            # a trial testing two names of one drug is one trial for that drug
            if key not in seen_here:
                seen_here.add(key)
                entry["trials"] += 1
            entry["names"][name] = entry["names"].get(name, 0) + 1
            rank, label = _furthest_phase(t.phase)
            if rank > entry["phase_rank"] or entry["lead_nct"] is None:
                if rank > entry["phase_rank"]:
                    entry["phase_rank"], entry["phase"] = rank, label
                entry["lead_nct"] = t.nct_id
            for c in (t.conditions or "").split(";"):
                if c.strip():
                    entry["conditions"].add(c.strip())

    out = []
    for entry in groups.values():
        names = entry.pop("names")
        # the name to show: one the FDA lists as an ingredient if there is one,
        # else the one the sponsor used most, then the longest — a generic name
        # is usually longer than the code it replaced
        display = max(names, key=lambda n: (n.casefold() in marketed,
                                            names[n], len(n)))
        out.append({
            **entry,
            "name": display,
            "also_known_as": sorted(n for n in names if n != display),
            "approved_as": next((marketed[n.casefold()] for n in names
                                 if n.casefold() in marketed), None),
            "conditions": sorted(entry["conditions"])[:3],
        })
    out.sort(key=lambda e: (-e["phase_rank"], -e["trials"], e["name"]))
    return out


def company_filings(db, ticker):
    """Every annual report held for a company, newest fiscal year first."""
    rows = db.query(Filing).filter(Filing.company_ticker == ticker).all()
    # sorted here rather than in SQL: a filing stored before periods were
    # recorded has no fiscal year, and the ordering must put those last
    # without depending on how a given backend sorts nulls.
    rows.sort(key=lambda f: (f.fiscal_year or -1, f.filed or ""), reverse=True)
    company = db.get(Company, ticker)
    cik = company.cik if company else None
    return [{
        "form": f.form,
        "filed": f.filed,
        "fiscal_year": f.fiscal_year,
        "period_end": f.period_end,
        "accession": f.accession,
        "document": f.document,
        "sections": (f.sections_found or "").split(",") if f.sections_found else [],
        "url": filing_url(cik, f.accession, f.document) if cik else None,
    } for f in rows]


def approved_products(db, ticker):
    """
    One row per marketed product rather than per Orange Book application: a
    drug listed under four dosage forms is one thing a reader recognises, and
    the earliest approval is the date it reached patients.
    """
    rows = (db.query(ApprovedProduct)
              .filter(ApprovedProduct.company_ticker == ticker).all())
    grouped = {}
    for r in rows:
        key = (r.trade_name or r.ingredient or "").strip()
        if not key:
            continue
        entry = grouped.setdefault(key, {
            "trade_name": r.trade_name,
            "ingredient": r.ingredient,
            "approval_date": r.approval_date,
            "applications": set(),
        })
        entry["applications"].add(r.appl_no)
        # the earliest approval, which is when the product actually arrived
        if r.approval_date and (entry["approval_date"] is None
                                or r.approval_date < entry["approval_date"]):
            entry["approval_date"] = r.approval_date
    out = [{**v, "applications": sorted(a for a in v["applications"] if a)}
           for v in grouped.values()]
    return sorted(out, key=lambda p: p["approval_date"] or "", reverse=True)


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
            fin_history = history_from_db(company)
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
                fin_history = financials.get("history") or {}
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
        # every year reported, newest first, alongside the single current
        # figure. Both are here because they answer different questions: what
        # the cash is, and whether it is running out.
        "financial_history": fin_history,
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
        # The filings this company's answers can be drawn from, newest first.
        # The count is the point as much as the list: five years per issuer is
        # the window, so a question about an earlier year has no source here
        # and should be refused rather than answered from the nearest filing.
        "filings": company_filings(db, ticker) if company is not None else [],
        # What is actually approved, as the FDA lists it. A pipeline built from
        # trials cannot show these — a marketed drug has stopped being a trial
        # — and showing only trials would make an approved portfolio look empty.
        "approved_products": approved_products(db, ticker) if company is not None else [],
        # what the trials test, grouped by the registry's own name for it. Not
        # a programme list — see studied_interventions.
        "interventions": studied_interventions(db, ticker) if company is not None else [],
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


@app.get("/source/chunk/{chunk_id}")
def source_chunk(chunk_id: int):
    """
    The exact passage a citation was drawn from, with the document it sits in.

    An answer quotes 600 characters and the rest is gone. This returns the whole
    chunk as stored, which is what the model was actually allowed to read, plus
    a link to the filing on EDGAR. The two are different kinds of check: one
    shows what we read, the other shows whether we read it correctly.
    """
    db = SessionLocal()
    try:
        row = (db.query(FilingChunk, Filing, Company)
                 .join(Filing, FilingChunk.filing_id == Filing.id)
                 .join(Company, Company.ticker == Filing.company_ticker)
                 .filter(FilingChunk.id == chunk_id).first())
        if row is None:
            raise HTTPException(status_code=404,
                                detail=f"No stored passage with id {chunk_id}.")
        chunk, filing, company = row
        # how many pieces the section was split into, so a reader can see this
        # is one passage of many rather than the whole of what the filing says
        siblings = [
            cid for (cid,) in
            db.query(FilingChunk.id)
              .filter(FilingChunk.filing_id == filing.id,
                      FilingChunk.section == chunk.section)
              .order_by(FilingChunk.ordinal).all()]
        total = len(siblings)
        return {
            "chunk_id": chunk.id,
            "text": chunk.text,
            "section": chunk.section,
            "ordinal": chunk.ordinal,
            "of": total,
            # every passage of this section, in order, so a reader can step
            # through the section rather than only see the one cited. Without
            # these the "1 of 71" is a fact you are told and cannot act on.
            "section_chunk_ids": siblings,
            "company": {"ticker": company.ticker, "name": company.name,
                        "cik": company.cik},
            "filing": {
                "form": filing.form, "filed": filing.filed,
                "fiscal_year": filing.fiscal_year,
                "period_end": filing.period_end,
                "accession": filing.accession,
                "document": filing.document,
                "url": (filing_url(company.cik, filing.accession, filing.document)
                        if company.cik else None),
            },
        }
    finally:
        db.close()


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
    result = compare_universe(store, names, pair[0], pair[1])
    # what produced each end, so a rule change is not read as an event
    result["provenance"] = snapshot_provenance(pair[0], pair[1])
    return result


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
