# Roadmap

Where this could go next. Nothing here is built yet except where noted. I keep it
out of the README so the README stays about what actually exists today.

## Phase 1 (done)

Real trial and financial data with no fabricated scores, a deterministic grounded
assessment, the LLM narrative layer that only phrases the facts, the sourced and
filtered company universe, the database and ingestion behind a filterable API, and
the two-level frontend (browse the universe, then drill into one company).

## Phase 2: change history (done, showing it in the app to go)

Done: every ingestion run archives what the APIs returned, one snapshot per
company per source under a dated key, and nothing overwrites an earlier date
(`app/raw_store.py`). So history is now actually being kept, in S3 when
`RAW_BUCKET` is set and on local disk otherwise.

Also done: the figures in a snapshot now actually move between runs. Cash is
taken from the most recent filing rather than the last annual report, so it
changes every quarter instead of once a year. Without that, diffing two snapshots
a month apart would have shown no financial change at all for eleven months of
the twelve.

Also done: `app/changes.py` reads two dates back out of the archive and reports
what moved, with no API call. Run against snapshots twelve days apart it found
275 of 478 companies changed: 392 figures updated as companies filed their
quarter, 69 trial status flips, 29 new registrations, one phase advance. The
individual events are the ones worth knowing about, a trial going to TERMINATED,
a programme moving from Phase 2 to Phase 3, several reaching COMPLETED.

`ingest.py --snapshot-only` captures a snapshot without writing to the database,
because writing replaces trial rows and drops their embeddings. History should
not cost a re-embed of everything.

One real limit came out of this. For a sponsor whose fetch was truncated we hold
the first 1,000 studies of several thousand, and the search does not return them
in a stable order, so a different subset arrives each run. Comparing them claimed
1,178 changes at Pfizer in a fortnight when seven trials had been registered. So
truncated sponsors report only their registry total, and say why. Asking the
search for a deterministic order would make the subset stable and is worth doing
before the next capture, though it would still only cover a fixed slice of a
large sponsor.

To do: show it. The API and the frontend still only describe the present, so the
changes exist in the archive and nowhere a reader can see them.

## Phase 3: monitoring (scheduling and detection done, alerting to go)

Deployed, with the schedule off: the two functions that turn a schedule into
ingestion work (`infra/lambdas/`). A schedule fires the dispatcher, which puts one message
per slice of the universe on a queue; the runner turns each message into a
container task running that slice. This is what keeps the long job out of a
Lambda's time limit. `ingest.py` takes `--shard N --of M` for exactly this.

Also done: detecting the changes worth telling someone about, which is Phase 2's
`app/changes.py`. A newly terminated trial, a programme reaching Phase 3 and a
quarter's figures moving all come out of it already.

To do: deploying it (Phase 6), and deciding what to do when something is found.
Everything so far writes to a report; nobody is told.

The measured cadence should set the schedule rather than a guess. Of 490 changes
over twelve days, 392 were companies filing their quarter, which cluster around
earnings rather than arriving evenly. The trial events, the ones actually worth
an alert, were a few dozen in a fortnight. So a daily run mostly finds nothing
and a weekly one loses little, which makes the current daily ScheduleExpression
in `pipeline.yaml` more than the data asks for.

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

## Phase 6: deployment (done, on plain HTTP)

Deployed to us-east-2 on 2026-09-07. Three stacks: `storage` holds what cannot be
rebuilt, `pipeline` holds the disposable ingestion machinery, and `serving` holds
the frontend behind a public load balancer with the API beside it on a private
Cloud Map name that resolves nowhere outside the VPC. Both run on Fargate, one
task each.

The database is deliberately not in the templates. It is an RDS Postgres 16
instance created by hand, restored from a 4.8 GB dump, and its life is not tied
to a stack that gets torn down and rebuilt. The HNSW index came across with the
dump, so the vector search answers in milliseconds rather than the five seconds a
sequential scan over 334,624 vectors takes.

/ask is the only endpoint that spends money, and it has a daily budget counted in
the database rather than in the process, because a counter in memory resets on
every deploy and two tasks each keep their own.

What the first deploy cost, all four of them the same shape, valid until
CloudFormation saw them: a quoted shell expansion that passed an empty argument,
an Fn::If with four arms, a security group rule the runbook put after the step
that needed it, and a column added to models.py after the dump was taken. All
four now have tests or a startup check.

To do: it is on the load balancer's own hostname over plain HTTP, and no
certificate is possible for a name AWS owns, so a domain is the next step and
should come before the URL is given to anyone. `DesiredCount` is 1 per service
with no autoscaling. The ingestion schedule ships `DISABLED` and needs an ingest
image in ECR before it is worth enabling. There is no WAF: the budget caps what a
day can cost, not how fast someone can ask.

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
