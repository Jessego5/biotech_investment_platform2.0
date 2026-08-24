# AI-Assisted Biotech Investment Platform

This is a small full-stack web app I built to browse and filter public biotech
companies by their pipeline stage and financials. Everything comes from real
primary-source data :) The data comes from two places:

- Clinical trials from the [ClinicalTrials.gov v2 API](https://clinicaltrials.gov/data-api/api)
- Financials from [SEC EDGAR](https://www.sec.gov/edgar/sec-api-documentation):
  R&D expense, cash, marketable securities, debt, operating cash flow, net
  income, revenue, and shares outstanding

## Why this exists

The whole point is that everything is grounded in real, stable, trusted data,
nothing is fabricated:

- The facts are computed directly. Trial counts by phase and status, the SEC
  figures above, and a runway estimate built from them, all from the primary
  sources, and each one says why so you can check it.
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

## Getting the data right

Most of the work in this project is not the app, it is making sure the numbers
mean what they claim to. Primary-source data is only trustworthy if you read it
correctly, and several ways of reading it wrong look completely normal until you
check. Each of these was found by comparing what the code returned against what
the filings actually say, and each one changed a conclusion the app was showing:

- **A fiscal year is not the year the data covers.** SEC tags every figure with
  the fiscal year of the *filing*, and one 10-K restates several prior years, all
  carrying the filing's year. Selecting on that field returned Recursion's 2023
  R&D as its 2025 figure: $241m instead of $475m, two years stale.
- **Cash is a balance, not a yearly total.** Reading it from the last annual
  report showed what a company had at its year end, not what it has now. For a
  biotech spending down cash every quarter that gap is large.
- **Cash is not the same as liquidity.** Biotechs hold most of their funding in
  marketable securities, reported separately. CRISPR Therapeutics has $291m of
  cash and $2.06b of securities, so runway from cash alone read as under a year
  when the real answer was closer to seven. The two are only added when reported
  as of the same date, because a company that stopped holding securities keeps
  its last figure in the record forever.
- **R&D expense is not cash burn.** It excludes G&A and includes non-cash charges,
  so it misses in both directions. Runway now divides by cash actually used in
  operations, and says so when it has to fall back.
- **A 404 does not mean the company lacks the thing.** Companies report the same
  figure under different XBRL tag names, so asking per tag cannot tell absence
  from a wrong guess. Fetching everything a company filed and selecting from it
  removes the guess.
- **Identifiers drift.** Tickers move in and out of SEC's ticker file as
  companies delist or restructure, so resolving by ticker silently loses
  companies over time. CIK is the stable key and is what the universe stores.
- **Pagination is not optional.** The trial search returns one page at a time.
  Taking the first page truncated every large sponsor: Pfizer registers 6,061
  studies and the app was storing 70.

Where the data is genuinely incomplete the app says so rather than presenting a
partial answer as a whole one: a truncated pipeline reports the sponsor's real
total, a figure with no recent filing is labelled with the date it does have, and
a company whose filings can't be parsed reads as unavailable, never as zero.

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
    models.py          # SQLAlchemy models (Company, Trial, Financial)
    database.py        # engine and session (SQLite by default, Postgres via DATABASE_URL)
    semantic.py        # meaning-based search: a pgvector query on Postgres, an
                       #   in-memory index on SQLite
    raw_store.py       # dated snapshots of what the APIs returned (S3 or local disk)
  build_company_universe.py  # sources and filters the universe into companies.json
  ingest.py            # loads the universe into the database
  embed_trials.py      # embeds trial text for the semantic chat
  evaluate.py          # the evaluation suite
  tests/               # unit tests (offline, no API keys, no network)
  Dockerfile           # one image, run as either the API or the ingestion batch
frontend/              # plain HTML/CSS/JS (browse view and detail view)
infra/
  lambdas/
    dispatch.py        # schedule -> one queue message per slice of the universe
    runner.py          # queue message -> one container task running that slice
  cloudformation/
    storage.yaml       # the durable half: snapshot archive, queue, dead-letter queue
    pipeline.yaml      # the disposable half: schedule, functions, cluster, task
    params/            # per-environment parameter files (dev, prod)
  deploy.sh            # packages the functions and deploys both stacks
docker-compose.yml     # local stack: Postgres + the API + a one-shot ingest
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
(`biotech.db`). Expect around fifteen minutes: it follows every page of trial
results and makes one request per company to SEC, both paced politely against
rate limits:

```bash
python ingest.py
```

If you already have a `biotech.db` from an earlier version, delete it first. The
company and financial tables gained columns (how many trials a sponsor really has,
and which period each financial figure covers), and `init_db` creates missing
tables but does not alter existing ones, so an old file fails on the first query
with "no such column". Re-ingesting is also the only way to pick up the
correctness fixes described above, since they all live in the fetch layer:

```bash
rm biotech.db && python ingest.py
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

## Running in a container

The steps above stay the only thing you need for local work. This is the same app
packaged to run somewhere else, which is the groundwork for scheduled ingestion.

The API and the ingestion batch are one image, not two. They share all their code
and their database config and differ only in the command they start with, so there
is no second image that can drift from the first:

```bash
docker compose up api             # http://localhost:8000, against Postgres
docker compose run --rm ingest    # same image, runs ingest.py, then exits
```

`docker-compose.yml` also brings up Postgres, which is the real point of it. Local
work runs on SQLite, and Postgres is the path that would fail quietly rather than
loudly: embeddings are stored through a type that resolves to `vector` on Postgres
and to a blob everywhere else, and only the blob half runs day to day.

Running the stack is what settles it. All six tables create, the `vector` extension
loads, `trials.embedding` and `filing_chunks.embedding` come back as `vector` rather
than `bytea`, and `<=>` returns 0.2857 for `[1,2,3]` against `[3,2,1]` — the cosine
distance the retrieval code assumes it is getting. Building it also turned up a real
bug: `WORKDIR` creates `/app` as root and `COPY --chown` only owns the files it
copies, so the image could read its own code but not create the SQLite file beside
it.

Both services take a `PIP_INDEX_URL` build argument, defaulting to PyPI. Point it at
a mirror where PyPI is slow; installing the dependencies is nearly all of the build.

`database.py` reads `DATABASE_URL` and falls back to the local SQLite file when it
isn't set, so running without Docker is unchanged and still needs no configuration.

The reason ingestion is a separate command rather than a background thread in the
API is that it is a long batch job: a few hundred companies, paced politely against
two rate-limited APIs. It belongs in something that can take minutes and exit, not
in a request handler.

## Snapshots, and running ingestion in slices

Ingestion now keeps what the APIs actually returned, not just what the database
columns hold. Every run writes one snapshot per company per source under a dated
key, and nothing overwrites an earlier date:

```
raw/clinicaltrials/2026-08-07/RXRX.json.gz
raw/sec/2026-08-07/RXRX.json.gz
```

Snapshots go to S3 when `RAW_BUCKET` is set and to `backend/raw/` otherwise, so
this needs no AWS account to try. The database rows are still wiped and replaced
each run, but the snapshots behind them accumulate, which is what makes change over
time answerable later. The trial payload is stored exactly as ClinicalTrials.gov
sent it, so a field this version of the code ignores can still be recovered by
re-parsing an old snapshot.

A run can also do part of the universe:

```bash
python ingest.py                    # all 552 companies
python ingest.py --shard 2 --of 8   # just this slice (69 companies)
```

Slices are dealt round-robin over a ticker-sorted universe, so they are the same no
matter what order `companies.json` is in, they never overlap, and together they are
exactly the whole universe. `SHARD_INDEX` and `SHARD_COUNT` do the same thing from
the environment, which is what a container task override can set.

## Scheduled ingestion

This is the part that is written but not deployed. Two small functions in
`infra/lambdas/` turn a schedule into container tasks:

```
EventBridge schedule
  -> dispatch.py    puts one message per slice on a queue, then exits
     -> SQS         retries, and a dead-letter queue for slices that keep failing
        -> runner.py  starts one ECS task per slice, then exits
           -> the same image, running `python ingest.py`
```

The reason it is shaped like this is timeouts. Ingesting the universe takes minutes,
well past what a Lambda is allowed to run, so the functions only do the parts that
take milliseconds (deciding the slices, starting the tasks) and the actual fetching
happens somewhere with no time limit. Slicing is also what makes the run finish in
a reasonable time without going faster against SEC than its rate limit allows: eight
tasks each doing sixty-nine companies, rather than one doing all 552.

Both functions are tested without AWS. Their real work is plain data (the queue
messages, the RunTask call), so the tests check that data directly and never need
credentials or a deployment.

## Deploying

Two CloudFormation stacks per environment, split by lifetime rather than by
service. `storage.yaml` holds the things that cannot be rebuilt: re-running
ingestion gets you today's data, never last month's, so the snapshot archive is
`DeletionPolicy: Retain` and lives apart from anything that gets redeployed.
`pipeline.yaml` holds everything disposable and imports what it needs from the
first, so replacing the pipeline can never take the history with it.

Nothing in either template branches on the environment. Everything that differs
(shard count, schedule, task size, log retention) is a row in one `Mappings`
table, so dev and prod really are the same template:

|            | dev        | prod              |
| ---------- | ---------- | ----------------- |
| shards     | 2          | 8                 |
| schedule   | weekly     | daily 06:00 UTC   |
| schedule   | `DISABLED` | `ENABLED`         |
| task size  | 0.5 vCPU   | 1 vCPU            |

Dev's schedule is off by default on purpose: a dev stack should not quietly fetch
the whole universe from SEC on a timer.

```bash
./infra/deploy.sh dev s3://my-deploy-artifacts 'postgresql+psycopg://...'
```

That packages the two functions, uploads them under a fresh key (pointing at an
unchanged key is the classic "I deployed and nothing changed"), and deploys both
stacks in order. The database URL is passed on the command line and stored in
Secrets Manager, so it is not in the committed parameter files and not readable in
the task definition.

The container image is a separate step, since it needs Docker and changes far less
often. The one thing to get right there is the architecture: building on an Apple
Silicon machine produces an ARM64 image, Fargate defaults to X86_64, and the
mismatch fails at task start with `exec format error` rather than at build time.
Build with `--platform linux/amd64`, or deploy with `CpuArchitecture=ARM64`.

The templates are unit tested. Not a substitute for a deploy, but it catches the
class of mistake that otherwise surfaces halfway through a rollback: an undeclared
`!Ref`, a `!GetAtt` on a resource that doesn't exist, and above all an import in
`pipeline.yaml` that `storage.yaml` never exports, which fails with a message that
names neither stack.

**None of this has been deployed.** It is written, checked, and unproven.

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

## Tests

Unit tests cover the deterministic core: the signal thresholds in `analysis.py`,
the fetch-and-parse layer in `data_sources.py`, and every filter, sort, and limit
in `retrieval.py`. Both ClinicalTrials.gov and SEC are faked, and the database
tests run against a seeded in-memory SQLite, so the suite runs offline in well
under a second and never touches `biotech.db` or needs an API key.

```bash
pip install -r requirements-dev.txt
pytest
```

The point is the boundaries. A runway of exactly 1.0x is "moderate", not "tight";
a 0.4 termination rate does not trip the high-termination flag; a company with no
financials returns `None`, never a fabricated zero. Those rules are what the app's
credibility rests on, so a label should only ever change because someone
deliberately changed the rule.

This is different from the evaluation suite below: the tests pin the deterministic
logic, the evaluation measures how the LLM layer behaves on top of it.

## Evaluation

There is a real evaluation suite. It uses ground truth computed straight from the database, independent of the system, and measures three checkable things: groundedness (is every claim in an answer backed by what was retrieved?), retrieval correctness (does the system's set match an independent true set, by precision and recall?), and refusal (does it decline ungroundable questions?).

```bash
python evaluate.py        # needs the OpenAI key
```

The methodology and the results, including where it does poorly, are in
[EVALUATION.md](EVALUATION.md).

## Some notes

- Around 550 companies, from a full sweep of the three biotech SIC codes filtered
  to the ones with a real pipeline and real financials. It is broad but not every
  public biotech.
- US-GAAP and IFRS filers both. A foreign private issuer files a 20-F and reports
  under `ifrs-full`, so a us-gaap-only lookup read BioNTech and GlaxoSmithKline as
  having no financials at all rather than as unreadable. IFRS tag names come last
  in each list, so a company reporting under both is never given a us-gaap
  numerator over an IFRS denominator. "Unavailable" now means genuinely absent.
- Financials come from one request per company (SEC's `companyfacts`), not one
  request per figure. That is a correctness decision rather than a speed one:
  companies report the same real-world figure under different XBRL tag names, and
  asking for a name a company doesn't use returns 404 whether or not it has the
  thing. Probing names therefore cannot tell absence from a wrong guess. Reading
  one 404 as "no debt" is how you confidently report a company has none when it
  has $586m. Fetching everything and selecting from what is actually there
  removes the guess, and makes each new figure free.
- Eight financial figures per company: R&D expense, cash, marketable securities,
  debt, operating cash flow, net income, revenue, and shares outstanding. They are
  two different kinds of number and are fetched differently. The period totals (spending, cash flow, revenue)
  only mean something over a full year, and quarterly filings report both the
  quarter and the year to date under the same tag, so "the newest one" is
  ambiguous. Balances (cash, share count) are a value on a date, so the newest one
  reported is right, usually from a 10-Q. Each is stored with the period it covers
  and shown that way: "R&D expense: $475,271,000 (FY2025, full year)" next to
  "Cash: $545,683,000 (as of 2026-06-30)".
- Runway divides *liquidity* by burn, not cash by burn. Biotechs hold most of
  their funding in marketable securities, which are as spendable as cash but
  reported separately: CRISPR Therapeutics shows $291m of cash against $2.06b of
  securities, so cash alone said under a year of runway when the real answer was
  nearly seven. The two are only added when reported as of the same date. A
  company that stopped holding securities keeps its last figure in the record
  forever, and Recursion's is from 2022 against cash from 2026, so adding it would
  invent $405m it spent years ago. A stale figure is excluded and said to be
  excluded. Debt is reported beside the runway rather than netted off it, since
  runway answers "how long can this be funded", not "what is left over"; a debt
  figure older than the cash figure is flagged as possibly repaid since.
- Runway divides cash by real burn, meaning cash actually used by operations,
  rather than by R&D expense. R&D is not a cash figure: it excludes G&A and
  everything else a company spends, and it includes non-cash charges like stock
  compensation, so it misses in both directions. Recursion reports $475m of R&D
  against $372m of cash actually used, so there it overstates the burn; a company
  with heavy G&A would go the other way. Where operating cash flow isn't reported
  the estimate still falls back to R&D, but says so and says the figure may be
  off either way. A company whose operations generate cash is labelled "cash
  generative" rather than given a runway, since it isn't running a balance down.
- Revenue splits the universe into two kinds of company that aren't comparable on
  any other measure: one selling a product, one spending toward a readout. A
  reported zero counts as pre-revenue; nothing filed makes no claim either way.
- Share counts come from the `dei` taxonomy, not `us-gaap`, because the figure
  that is reliably present is the one on every filing's cover page.
- Two things this got wrong until recently, both worth knowing about because they
  moved real numbers. Cash was taken from the last annual report, so a company
  that had spent down its cash for two quarters still showed its year-end figure.
  And the annual R&D lookup selected on the entry's `fy` field, which is the
  fiscal year of the *filing*, not of the data: one 10-K restates several years of
  comparatives and all of them carry the filing's year, so it often picked a
  figure two years stale. Understating the burn overstates runway, so companies
  read as healthier than they were. Recursion's runway went from 3.1x to 1.15x
  once both were fixed, which changes its label from "comfortable" to "moderate".
- Trial fetching follows every page of results, so a sponsor is no longer cut off
  at the first page. There is still a ceiling of 1,000 studies per sponsor, since
  a few giants register far more than that (Pfizer is over six thousand) and one
  company should not dominate a run. When the ceiling is hit, the fetched
  snapshot records the sponsor's real total and marks itself truncated. Nothing
  displays that yet: the database stores only the trials themselves, so the app
  still shows a truncated pipeline without saying it is truncated. Surfacing it
  needs a column on the company row, which is the next piece of this.
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
