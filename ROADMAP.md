# Roadmap

Where this could go next. Nothing here is built yet except where noted. I keep it
out of the README so the README stays about what actually exists today.

## Phase 1 (done)

Real trial and financial data with no fabricated scores, a deterministic grounded
assessment, the LLM narrative layer that only phrases the facts, the sourced and
filtered company universe, the database and ingestion behind a filterable API, and
the two-level frontend (browse the universe, then drill into one company).

## Phase 2: change history (storage done, diffing to go)

Done: every ingestion run archives what the APIs returned, one snapshot per
company per source under a dated key, and nothing overwrites an earlier date
(`app/raw_store.py`). So history is now actually being kept, in S3 when
`RAW_BUCKET` is set and on local disk otherwise.

Also done: the figures in a snapshot now actually move between runs. Cash is
taken from the most recent filing rather than the last annual report, so it
changes every quarter instead of once a year. Without that, diffing two snapshots
a month apart would have shown no financial change at all for eleven months of
the twelve.

To do: read two dates back and diff them into the changes a person would care
about, then show that. The database rows are still wiped and replaced on each
ingest, which is fine while the snapshots behind them are the source of truth,
but showing change in the app means either diffing snapshots on read or storing
several versions of a row.

## Phase 3: monitoring (scheduling written, alerting to go)

Written but not deployed: the two functions that turn a schedule into ingestion
work (`infra/lambdas/`). A schedule fires the dispatcher, which puts one message
per slice of the universe on a queue; the runner turns each message into a
container task running that slice. This is what keeps the long job out of a
Lambda's time limit. `ingest.py` takes `--shard N --of M` for exactly this.

To do: the CloudFormation to actually create the queue, cluster, task definition
and schedule (Phase 6), then the part that matters here, which is detecting the
changes worth telling someone about (a Phase 3 readout, a newly terminated trial,
a big drop in cash) and alerting on them.

## Phase 4: backtesting (last, and blocked on most of the rest)

The real question: did these grounded signals actually relate to later outcomes
like trial success or approvals? This is where "grounded but simple" gets tested
against reality, and it is deliberately the final phase.

It is not blocked on waiting for history. SEC returns every period a company ever
filed, and a trial record carries its own outcome, so the past can be
reconstructed rather than waited for. What it is blocked on:

- the wider trial registry (Phase 7), since "did a Phase 3 follow, and did a
  competitor get there first" needs trials outside these 480 companies
- a historical company universe. The universe is currently sourced from EDGAR's
  *current* ticker file, so companies that went bankrupt or were acquired are
  missing. Testing whether a short runway predicts trouble against a sample that
  excludes the companies which ran out of money would answer the wrong question.
- a point-in-time lookup that filters on when a figure was *filed* rather than
  the period it covers, or the reconstruction uses information that wasn't public
  yet and every signal looks prescient.

The first outcome to test is trial advancement (did a Phase 2 lead to a Phase 3 in
the same indication), because it needs no source beyond the two already used.
Stock moves are the most intuitive outcome and the noisiest; they are not the
place to start.

## Phase 5: semantic search (trial text done, filings to go)

Done: semantic search over trial descriptions (summary, conditions, interventions,
eligibility), embedded with OpenAI, so questions like "which trials involve CAR-T?"
get real answers. Storage and search follow whichever database is behind it: a
pgvector column that Postgres searches directly, or raw float32 bytes and an
in-memory FAISS index on SQLite, which is what runs locally today.

To do (heavier): chunk and embed the SEC 10-K narrative (Risk Factors, MD&A) for
questions like "what does this company say are its biggest risks?". The filings
are long and need fetching and chunking, so it is more work and more fragile.
Worth doing on the 480 companies already stored first, since that is the same
technique at a size still small enough to check by hand.

## Phase 7: the whole trial registry

Right now the universe is trials sponsored by 480 biotech companies, which is
12,943 studies, or 2.2% of the 597,691 registered on ClinicalTrials.gov. Ingesting
all of them turns the app from "these companies' pipelines" into "search every
clinical trial", which is a considerably more useful thing and is the direction
this should go.

Measured, so the size is not a guess:

- 6.1 GB stored, of which 3.6 GB is embedding vectors
- about $5 of embeddings, one off
- roughly 598 requests to fetch it all, at 1,000 studies a page

The fetch is cheap. What breaks is the vector search: 3.6 GB of vectors cannot
sit in memory in a FAISS index the way 12,943 do today. That is the real
constraint, and it is what pushed the schema to pgvector, which is now in place:
the embedding column is a real vector on Postgres and the search is a query
rather than a rebuild. What is still needed is a host with actual memory and
snapshots in object storage rather than on a laptop.

The measurement behind that: the in-memory index takes about 4.7 seconds to build
on the first query after a process starts, against 1 second once warm. That cost
scales with the number of vectors and is paid again on every restart, which on a
container platform is routine.

Note what this does NOT need: sharded parallel ingestion. 598 requests is under
half an hour on one machine, so `infra/` stays unnecessary for this phase.

## Phase 8: SEC filing text at scale

The phase that makes the ingestion pipeline in `infra/` justified rather than
decorative. Chunking and embedding filing narrative across a wide set of filers,
re-processed as new filings arrive, is continuous work of unpredictable size,
which is exactly the shape the queue and the container tasks were built for. Until
then the honest description of `infra/` is that it is written, tested, and not yet
needed.

## Phase 6: deployment (written end to end, never deployed)

Done in code: the app reads `DATABASE_URL` and falls back to local SQLite when it
isn't set, so Postgres needs no code change. The API and the ingestion batch are
one image (`backend/Dockerfile`) that differ only in the command they start with,
and `docker-compose.yml` brings that up against a local Postgres. The whole
ingestion pipeline is described in CloudFormation (`infra/cloudformation/`), split
into a durable stack (archive, queue, dead-letter queue) and a disposable one
(schedule, functions, cluster, task), parameterized so dev and prod are the same
template with a different row in one mappings table. `infra/deploy.sh` packages
and deploys it.

To do: the database itself is not in the templates. They take a `DATABASE_URL`
and store it in Secrets Manager, which works with RDS, Aurora Serverless, or
anything else, but something has to create it. Then deploying the API and the
frontend, which is still not described anywhere.

The honest status: this is all written and unit tested and none of it has ever
run. No image has been built, nothing has talked to a real Postgres, and no AWS
call has been made. The tests check the data these pieces produce, not that AWS
accepts it.

## Other ideas

- Use the trial fields already being fetched and thrown away: start and completion
  dates above all, since "Phase 3, expected readout Q2 2026" is a far more useful
  fact than "Phase 3, recruiting", plus enrollment and whether results were posted.
  This costs no extra requests, the data is already in every response.
- Market cap and cash per share, now that share counts are stored. Cash per share
  needs nothing further; market cap needs a price source, which is the first
  thing here that would add a third API.
- Parse IFRS 20-F filers like BioNTech so foreign issuers show real financials.
- Better sponsor-name matching for companies that register trials under a subsidiary.
- Let you compare two companies side by side.
