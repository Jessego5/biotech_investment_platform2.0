# Roadmap

Where this could go next. Nothing here is built yet except where noted. I keep it
out of the README so the README stays about what actually exists today.

## Phase 1 (done)

Real trial and financial data with no fabricated scores, a deterministic grounded
assessment, the LLM narrative layer that only phrases the facts, the sourced and
filtered company universe, the database and ingestion behind a filterable API, and
the two-level frontend (browse the universe, then drill into one company).

## Phase 2: change history

The schema is already history-friendly since every row has timestamps. The next
step is to actually store several snapshots per company instead of wiping and
replacing on each ingest, so I can show change over time: new trials,
terminations, cash moves.

## Phase 3: monitoring

Re-fetch on a schedule, detect the changes a person would care about (a Phase 3
readout, a newly terminated trial, a big drop in cash), and alert when one happens.

## Phase 4: backtesting

Once there is history, ask the real question: did these grounded signals
actually relate to later outcomes like approvals, trial success, or stock moves?
This is where "grounded but simple" gets tested against reality.

## Phase 5: semantic search (trial text done, filings to go)

Done: semantic search over trial descriptions (summary, conditions, interventions,
eligibility), embedded with OpenAI, stored in SQLite, and searched with a FAISS index, so
questions like "which trials involve CAR-T?" get real answers.

To do (heavier): chunk and embed the SEC 10-K narrative (Risk Factors, MD&A) for
questions like "what does this company say are its biggest risks?". The filings
are long and need fetching and chunking, so it is more work and more fragile.

## Phase 6: deployment

Move from SQLite to Postgres (the models already port over), deploy the API and
frontend, and run ingestion on a schedule. Not started, everything is local so far
on purpose.

## Other ideas

- Parse IFRS 20-F filers like BioNTech so foreign issuers show real financials.
- Better sponsor-name matching for companies that register trials under a subsidiary.
- Let you compare two companies side by side.
