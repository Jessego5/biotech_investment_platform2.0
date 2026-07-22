# Biotech Investment Agent

This is a small full-stack web app I built to browse and filter public biotech
companies by their pipeline stage and financials. Everything comes from real
primary-source data :) The data comes from two places:

- Clinical trials from the [ClinicalTrials.gov v2 API](https://clinicaltrials.gov/data-api/api)
- Financials (R&D expense, cash) from [SEC EDGAR](https://www.sec.gov/edgar/sec-api-documentation)

## Why this exists

The whole point is that everything is grounded in real, stable, trusted data,
nothing is fabricated:

- The facts are computed directly. Trial counts by phase and status, R&D expense,
  cash, and a rough cash vs burn runway proxy, all from the primary sources, and
  each one says why so you can check it.
- The LLM only phrases those facts. It never invents a number and never gives buy
  or sell advice. With no API key set it falls back to a fixed template, so the
  app never depends on the LLM.
- The company list is sourced, not hand-picked. `build_company_universe.py` asks
  EDGAR which companies file under biotech SIC codes and keeps only the ones that
  actually have both a real pipeline and real financials.
- It is a real database-backed tool, not a single lookup. Ingestion loads the
  whole universe into a local database and the API lets you filter across it.

Scope is public companies only, since those are the ones with real free filings.
Private companies are out of scope on purpose.

## Layout

```
backend/
  app/
    main.py            # FastAPI app: /companies (filter) and /company/{ticker}
    data_sources.py    # ClinicalTrials.gov and SEC EDGAR fetching
    analysis.py        # turns the real data into grounded signals
    narrative.py       # grounded LLM narrative (only phrases the facts)
    retrieval.py       # shared DB query used by /companies and the chat
    chat.py            # grounded RAG chat (query plan, then answer from real rows)
    semantic.py        # meaning-based search over trial text
    models.py          # SQLAlchemy models (Company, Trial, Financial)
    database.py        # engine and session (SQLite dev, Postgres-ready)
  build_company_universe.py  # sources and filters the universe into companies.json
  ingest.py            # loads the universe into the database
  embed_trials.py      # embeds trial text for the semantic chat
  evaluate.py          # the evaluation suite
frontend/              # plain HTML/CSS/JS (browse view and detail view)
ROADMAP.md             # future phases
```

## How to run

### 1. Install

```bash
cd backend
python -m venv venv && source venv/bin/activate    # optional
pip install -r requirements.txt
```

Set up your `.env` (it is gitignored, so nothing here goes public):

```bash
cp .env.example .env
```

Then edit `backend/.env`:
- `SEC_USER_AGENT` is required. EDGAR wants automated requests to identify
  themselves with a real email and rejects fake ones, so set it to your own email.
- `OPENAI_API_KEY` is optional. The narrative works without it (it falls back to a
  template), but the chat and the trial embeddings need it.

### 2. Populate the database

`companies.json` is already committed, so you can go straight to ingestion. This
fetches trials and financials for the whole universe into a local SQLite file
(`biotech.db`). It takes a couple of minutes:

```bash
python ingest.py
```

To re-source the universe from scratch first, run `python build_company_universe.py`.

### 3. (optional) Embed trial text for the semantic chat

This lets the chat answer free-text questions like "which trials involve CAR-T?".
It needs an OpenAI key and costs a few cents. It resumes safely if interrupted:

```bash
python embed_trials.py
```

Without it the chat still handles structured questions, just not the semantic ones.

### 4. Start the API and frontend

```bash
uvicorn app.main:app --reload          # http://127.0.0.1:8000
cd ../frontend && python devserve.py   # http://127.0.0.1:5501
```

I use `devserve.py` for the frontend because it turns off browser caching, so
edits show up on a normal refresh (plain `python -m http.server` caches too hard).

## API

- `GET /companies` filters the universe. All params are optional and AND together:
  `min_rd`, `min_cash` (raw dollars), `has_phase3` (bool), `min_active_trials`
  (int), `sector`. Served from the database.
- `GET /company/{ticker}` gives the full grounded assessment and LLM narrative. It
  reads the database first and falls back to a live fetch if the ticker is not
  stored yet.
- `POST /ask` is the grounded chat (`{"question": "..."}`). Needs an OpenAI key.

## Grounded chat

The "Ask the data" box lets you ask questions in plain English. It is a grounded
chatbot: the LLM never answers from its own memory. It turns your
question into a query plan, runs that plan against the real database, and phrases
an answer using only the rows that came back, with the companies it used shown as
clickable receipts. It picks the right lookup for each question:

- Structured questions (phase, financials, filtering, counts, one company) become
  a real database query, exact and complete.
- Free-text questions (mechanisms, conditions, therapies like CAR-T) use semantic
  search over the trial text. A similarity floor means an off-topic question gets
  an honest "I don't have data on that" instead of the nearest wrong trial.

Predictions and buy/sell questions are refused. The filterable universe is still
the front door, the chat sits on top of it.

## Evaluation

There is a real evaluation suite. It uses ground truth computed straight from the database, independent of the system, and measures three checkable things: groundedness (is every claim in an answer backed by what was retrieved?), retrieval correctness (does the system's set match an independent true set, by precision and recall?), and refusal (does it decline ungroundable questions?).

```bash
python evaluate.py        # needs the OpenAI key
```

The methodology and the results, including where it does poorly, are in
[EVALUATION.md](EVALUATION.md).

## Some notes

- Around 480 companies, from a full sweep of the three biotech SIC codes filtered
  to the ones with a real pipeline and real financials. It is broad but not every
  public biotech.
- US-GAAP filers only for financials. Foreign issuers filing under IFRS (like
  BioNTech, which files a 20-F) come back as "unavailable", not made up.
- Large-cap trial counts are capped at 100 studies per sponsor, so big pharma is
  undercounted.
- Sponsor matching strips corporate suffixes (so "FATE THERAPEUTICS INC" matches
  "Fate Therapeutics"), but a company that registers under a subsidiary (Moderna
  files as "ModernaTX") needs a manual override in `main.py` and `ingest.py`.

## Limitations and future work

See [ROADMAP.md](ROADMAP.md). Short version: public companies only by design, and
the database schema is history-friendly (timestamps on everything) so later phases
like change history, monitoring, backtesting, and deployment are possible without
a redesign. None of those are built yet.

## Disclaimer

Informational only, grounded in ClinicalTrials.gov and SEC EDGAR data. Not
investment advice :)
