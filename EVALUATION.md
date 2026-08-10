# Evaluation

How I evaluate the system and why the numbers mean something. The core rule: the
ground truth is computed straight from the real database, on its own, so a metric
can't pass just because the system agrees with itself. If something can't be checked
against independent ground truth, the suite does not measure it (which rules out "is
this the right investment call?", there is no ground truth for that).

Run it with `python evaluate.py` (from `backend/`, needs an OpenAI key). The
questions live in `eval_questions.py`. Three dimensions:

1. **Groundedness.** Does every claim in an answer appear in what was retrieved? The
   suite pulls the checkable claims out of the answer (dollar figures, counts, NCT
   ids, statuses) and checks each one is in the retrieved text. Unsupported claims
   are printed as possible hallucinations.
2. **Retrieval correctness.** For structured questions, `eval_questions.py` computes
   the true set of companies directly from the raw Trial and Financial rows (its own
   code, not the system's `query_companies`), then compares it to the system's set by
   precision, recall, and exact match. This checks that the model turns a question
   into the right database query.
3. **Refusal.** Ungroundable questions (stock predictions, buy/sell advice, FDA odds)
   should be declined, not answered with a made-up number.

## Results

Run `python evaluate.py` to get them. Scores are not written down here on purpose:
an LLM translates every question, so they move between runs, and a number copied
into a file goes stale the moment anything downstream of it changes. The suite
prints its own summary, including the questions it got wrong.

What is worth recording is the shape of the failures, since those are stable even
when the scores are not.

### Where it fails: numeric thresholds

The weakest of the three dimensions is retrieval, and within it, turning a
question into the right query. The planner is inconsistent at pulling a number out
of a question. Asked for companies with more than a year of runway it sets the
filter correctly and matches the independent truth set exactly; asked the same
question with a different threshold it has returned every company in the universe,
having set no filter at all.

So it is capable of that query and unreliable at it, rather than unable, and the
weakness is threshold extraction rather than the filter behind it.

That failure is also a good argument for not reading recall alone. Returning the
whole universe scores a perfect recall while being useless, because a set that
contains everything cannot miss anything. Precision and exact match are what catch
it.

## Defects it caught

- A rounding edge: "more cash than annual R&D" returned BEAM (runway 0.9977), because
  the runway proxy was rounded to 1.0 before filtering. Fixed by filtering on the
  exact ratio and rounding only for display.
- A claim-checker false positive: "more than 30 active trials" made the checker flag
  the threshold "30" as unsupported. Fixed by skipping numbers after comparison words.
- A stale definition in the ground truth itself. When runway changed from
  cash / R&D to liquidity / cash burn, the truth function still computed the old
  one. Because the ground truth is deliberately independent code, it did not follow
  the change automatically, and marked the app badly wrong on that question while
  the app was behaving correctly. Independence is the point of the design, and
  this is its cost: a change to a definition has to be made in both places on
  purpose.

## Limitations

- Retrieval correctness is not deterministic, since an LLM translates the question.
  Exact match moves between runs when the model phrases a query slightly
  differently, which is why the scores are not recorded here.
- Recall alone can flatter a bad answer, as the threshold failure above shows, so
  it is never read on its own.
- Groundedness only checks the cleanly verifiable claim types (money, counts, NCT ids, statuses); free prose is not scored.
- Retrieval correctness only applies to structured questions, where independent groundtruth exists. Semantic search has no exact ground-truth set, so it is checked only through groundedness.
- The question set is small and fixed on purpose. Adding more is easy.
