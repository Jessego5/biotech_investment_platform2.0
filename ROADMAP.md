# Roadmap

Most of this is built. What follows is what each phase delivered, in one table,
then the five things actually open and what each is waiting on. The measurements
behind the built rows live in [README.md](README.md), [PIPELINE.md](PIPELINE.md)
and [EVALUATION.md](EVALUATION.md) and are not repeated here.

## Built

| | Delivered | Where |
|---|---|---|
| **1 · Data and universe** | Real trial and financial data with no fabricated scores, a deterministic grounded assessment, the narrative layer that only phrases facts, the sourced company universe, and the two-level frontend: browse the universe, then drill into one company. | `backend/app/`, `app/` |
| **2 · Change history** | Every ingestion run archives what the APIs returned, one snapshot per company per source under a dated key, and nothing overwrites an earlier date. Cash is read from the most recent filing rather than the last annual report, so figures move quarterly instead of once a year. A differ reads two dates back out of the archive with no API call. | `app/raw_store.py`, `app/changes.py` |
| **3 · Scheduling and detection** | A schedule fires a dispatcher that puts one message per slice of the universe on a queue; a runner turns each message into a container task for that slice, which is what keeps a long job out of a Lambda's time limit. Detection is Phase 2's differ. | `infra/lambdas/`, `ingest.py --shard N --of M` |
| **5 · Semantic search** | Trial descriptions embedded, and the heavier half: 10-K narrative chunked and embedded across 3,614 filings and 787 companies, 334,624 passages over Risk Factors, MD&A and intellectual property. | `app/semantic.py`, `embed*.py` |
| **6 · Deployment** | us-east-2, 2026-09-07. Three stacks split by lifetime: `storage` for what cannot be rebuilt, `pipeline` for disposable ingestion machinery, `serving` for the frontend behind a public load balancer with the API beside it on a private Cloud Map name. The database sits outside the templates on purpose. `/ask` carries a daily budget counted in the database, not in the process, because a counter in memory resets on deploy and two tasks each keep their own. | `infra/cloudformation/`, [DEPLOY.md](DEPLOY.md) |
| **7 · The wider registry** | 112,812 industry-sponsored interventional studies, against the 30,823 led by the universe. The two tables are kept apart because every pipeline count is computed from `trials`, and a competitor's Phase 3 landing there would quietly become somebody else's pipeline. 6.1 GB stored, 3.6 GB of it vectors, about $5 of embeddings, roughly 598 requests. | `registry_trials` |
| **8 · Filing text at scale** | The phase that made the queue and container tasks justified rather than decorative: chunking and embedding filing narrative is continuous work of unpredictable size. Vector search is an HNSW index rather than a scan, 4,763 ms against 2 ms, which is the figure that decided the database instance size. | `app/filings.py`, `embed_filings.py` |
| **9 · Retrieval quality** | The one component with no number attached to it now has one. A known-item test where a model writes the question a passage answers, so the passage is the right answer by construction. It found that one line of metadata beat every retrieval technique tried. | `eval_retrieval.py` |

Two things learned in Phase 2 are worth keeping in view. Run against snapshots
twelve days apart, the differ found 275 of the 478 companies in that capture had
changed: 392 figures updated as companies filed their quarter, 69 trial status
flips, 29 new registrations, one phase advance. And for a sponsor whose fetch was
truncated we hold the first 1,000 studies of several thousand in no stable order,
so comparing two captures claimed 1,178 changes at Pfizer in a fortnight when
seven trials had been registered. Truncated sponsors now report only their
registry total, and say why.

Not built, and deliberately: the other ~485,000 registry studies, which are
academic and government sponsored. The industry subset is what a question about a
competitor is actually asking about.

## Open

### Show the change history in the app

The archive accumulates, the differ reads it, and `/changes`,
`/company/{ticker}/changes` and `/snapshots` all serve it. Nothing renders it.
The only what-changed screen is the artboard at `/companies/fixture/what-changed`,
which is built on invented data and 404s in production, so the gap is a frontend
that never consumes an API that is already there.

Worth doing first: ask ClinicalTrials.gov for a deterministic order, so a
truncated sponsor returns the same slice each run. That makes the subset stable,
though it still only covers a fixed slice of a large sponsor.

### Decide what happens when a change is found

Everything so far writes to a report; nobody is told. Detection works — a newly
terminated trial, a programme reaching Phase 3, a quarter's figures moving all
come out of the differ already.

The measured cadence should set the schedule rather than a guess. Over twelve
days the differ found 275 of 478 companies changed, and of the 491 changes 392
were figures moving as companies filed their quarter, which cluster around
earnings rather than arriving evenly. The trial events, the ones actually worth
an alert, were 99: 69 status flips, 29 new registrations, one phase advance. A daily run mostly finds nothing and a
weekly one loses little, which makes the daily `ScheduleExpression` in
`pipeline.yaml` more than the data asks for. The schedule also ships `DISABLED`
and needs an ingest image in ECR before enabling it is worth anything.

### Ship contextual embeddings

`embedding_ctx` is populated for all 334,624 passages and the shipping search
still reads `embedding`, so both spaces exist side by side and the switch is a
flag rather than a migration.

Two things should be measured first. The reranker costs accuracy on named
questions and is the only lift on topical MRR worth its latency, taking 0.085 to
0.104 where hybrid manages 0.088 for the same two seconds, and `chat.py` already
knows which kind of question it has, so choosing per question is the configuration
the evidence points at and nobody has measured. And the production path usually
passes a ticker, which supplies the same identity by another route; that case is
unmeasured and it decides how much of the gain survives a real caller.

### A domain and a certificate

The deployment is on the load balancer's own hostname over plain HTTP, and no
certificate is possible for a name AWS owns, so this should come before the URL is
given to anyone. `DesiredCount` is 1 per service with no autoscaling, and there is
no WAF: the daily budget caps what a day can cost, not how fast someone can ask.

### Backtesting

Did these grounded signals actually relate to later outcomes like trial success or
approvals? This is where "grounded but simple" gets tested against reality, and it
is deliberately last.

It is not blocked on waiting for history. SEC returns every period a company ever
filed and a trial record carries its own outcome, so the past can be reconstructed
rather than waited for. Phase 7 cleared the registry blocker — "did a Phase 3
follow, and did a competitor get there first" now has trials outside the 787
companies to look at. What remains:

- **A historical company universe.** The universe is sourced from EDGAR's
  *current* ticker file, so companies that went bankrupt or were acquired are
  missing. Testing whether a short runway predicts trouble against a sample that
  excludes the companies which ran out of money answers the wrong question.
- **A point-in-time lookup** that filters on when a figure was *filed* rather than
  the period it covers, or the reconstruction uses information that was not public
  yet and every signal looks prescient.

The first outcome to test is trial advancement, did a Phase 2 lead to a Phase 3 in
the same indication, because it needs no source beyond the two already used. Stock
moves are the most intuitive outcome and the noisiest; they are not the place to
start.

## Other ideas

- Use the trial fields already being fetched and thrown away: start and completion
  dates above all, since "Phase 3, expected readout Q2 2026" is a far more useful
  fact than "Phase 3, recruiting", plus enrollment and whether results were posted.
  This costs no extra requests, the data is already in every response.
- Market cap and cash per share, now that share counts are stored. Cash per share
  needs nothing further; market cap needs a price source, which is the first thing
  here that would add a third API.
- Parse IFRS 20-F filers like BioNTech so foreign issuers show real financials.
- Better sponsor-name matching for companies that register trials under a subsidiary.
- Compare two companies side by side.
