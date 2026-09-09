# Roadmap

Most of this is built. The measurements behind it live in [README.md](README.md),
[PIPELINE.md](PIPELINE.md) and [EVALUATION.md](EVALUATION.md).

## Built

- **Data and universe.** Real trial and financial figures, no fabricated scores, a
  deterministic assessment, and a narrative layer that only phrases facts.
- **Change history.** Every run archives what the APIs returned under a dated key
  and never overwrites one, so two dates can be diffed with no API call.
- **Scheduled ingestion.** A dispatcher slices the universe onto a queue, a runner
  turns each slice into a container task, which keeps a long job out of a Lambda.
- **Semantic search.** Trial text, and the heavier half: 3,614 annual reports
  chunked into 334,624 embedded passages.
- **The wider registry.** 112,812 industry-sponsored studies, kept in their own
  table so a competitor's Phase 3 can never become somebody else's pipeline.
- **Deployment.** Three stacks split by lifetime, the database deliberately
  outside them, and a daily budget on the one endpoint that spends money.
- **Retrieval quality.** A known-item eval, which found that one line of metadata
  beat every retrieval technique tried.

Two measurements from that work are worth keeping in view, because they set what
comes next:

- Over twelve days, 275 of 478 companies changed. Of 491 changes, 392 were
  figures moving as companies filed their quarter. The trial events, the ones
  worth an alert, were 99.
- For a sponsor whose fetch was truncated we hold the first 1,000 studies of
  several thousand in no stable order, so two captures claimed 1,178 changes at
  Pfizer when seven trials had been registered. Truncated sponsors now report
  only their registry total, and say why.

Not built, deliberately: the other ~485,000 registry studies, which are academic
and government sponsored. The industry subset is what a question about a
competitor is actually asking.

## Open

**Show the change history.** `/changes`, `/company/{ticker}/changes` and
`/snapshots` all serve it and nothing renders it. The only what-changed screen is
an artboard on invented data that 404s in production. This is the largest gap
between what the system holds and what a reader can see, and it needs a route
handler as well as a page, since the browser never reaches the API directly.

**Measure retrieval with the ticker filter on.** Contextual embeddings took the
right document from 55.0% to 96.7% and `embedding_ctx` is already populated for
every passage, so switching is a flag. But `chat.py` resolves a company and
`semantic.py` then filters on it, so the shipping search is usually scoped to one
company already, and a `WHERE` clause supplies the identity the context line was
added to recover. The eval measured the unscoped case. Until the scoped one is
measured, shipping this is acting on a number taken under conditions the system
avoids by construction.

**Decide what happens when a change is found.** Everything writes to a report and
nobody is told. The measured cadence argues against the daily schedule in
`pipeline.yaml`: a daily run mostly finds nothing and a weekly one loses little.
The schedule also ships `DISABLED` and needs an ingest image in ECR first.

## Further off

**Backtesting.** Whether these signals related to later outcomes. Deliberately
last, and not blocked on waiting for history: the database holds fiscal years
back to 2002, because SEC returns every period a company ever filed, and a trial
record carries its own outcome. What it is blocked on is two narrower things:

- **A historical universe.** The 22 years of history are 22 years for the 787
  companies that exist *now*. The universe is built from SEC's current ticker
  file, so a company that went bankrupt in 2019 was never fetched and has no row
  at all. Asking whether a short runway predicted trouble, against a sample built
  from survivors, deletes the clearest confirmations from the denominator and
  makes any signal look better than it was.
- **A point-in-time lookup** filtering on when a figure was *filed* rather than
  the period it covers, or every signal looks prescient.

Trial advancement is the first outcome to test, since it needs no source beyond
the two already used. Stock moves are the most intuitive and the noisiest.

## Ideas

- Market cap and cash per share. Cash per share needs nothing further; market cap
  needs a price source, which would be the first third API.
- Better sponsor matching for companies registering trials under a subsidiary.
- Compare two companies side by side.
