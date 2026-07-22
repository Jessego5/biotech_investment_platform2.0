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

## Results (representative run, LLM output varies)

| Metric | Result |
|---|---|
| Groundedness | ~100% |
| Retrieval precision / recall | ~100% / 100% |
| Retrieval exact-match | 83% to 100% (varies, see below) |
| Refusal | 100% (6/6) |

## Defects it caught

- A rounding edge: "more cash than annual R&D" returned BEAM (runway 0.9977), because
  the runway proxy was rounded to 1.0 before filtering. Fixed by filtering on the
  exact ratio and rounding only for display.
- A claim-checker false positive: "more than 30 active trials" made the checker flag
  the threshold "30" as unsupported. Fixed by skipping numbers after comparison words.

## Limitations

- Retrieval correctness is not deterministic, since an LLM translates the question.
  Precision and recall stay high, but exact-match moves (one run 83%, another 100%)
  when the model phrases a query slightly differently.
- Groundedness only checks the cleanly verifiable claim types (money, counts, NCT ids, statuses); free prose is not scored.
- Retrieval correctness only applies to structured questions, where independent groundtruth exists. Semantic search has no exact ground-truth set, so it is checked only through groundedness.
- The question set is small and fixed on purpose. Adding more is easy.
