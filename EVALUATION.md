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

## Retrieval quality (the text side)

Everything above measures the structured half: questions whose true answer can be
computed from the raw rows. The text half — ranking 334,624 filing passages — had
no number attached to it at all, which meant the hardest component was also the
only unmeasured one. `eval_retrieval.py` fixes that.

### How the labels are made

Nobody has labelled this corpus and labelling it by hand is not on, so the labels
come from the corpus itself. Take a passage, have a model write the question that
passage answers, then throw the question at all 334,624 and see whether that exact
passage comes back. The passage is the right answer by construction, so no human
has to judge relevance.

Three things keep this from flattering itself:

- **The query set is generated once and stored** (`eval_retrieval_set.json`, 120
  passages stratified across risk factors, MD&A and intellectual property). Every
  run reads it. A set regenerated per run would hide a regression inside its own
  sampling noise, and a before/after is worthless if the two were asked different
  questions.
- **Each passage gets two questions.** The *named* one mentions the company, which
  is how people ask; the *topical* one deliberately does not, leaving the searcher
  to find one passage in 334,624 on subject matter alone. They measure different
  things and are never averaged together.
- **The floor is applied afterwards, not during.** Retrieval runs with the
  relevance floor off so that a passage which ranked first and was then cut is
  distinguishable from one that never ranked. Those two failures have opposite
  fixes.

Passages overlap by 300 characters and usually continue the same argument, so
landing on the chunk next door is not the same kind of miss as landing in another
company's filing. Exact, adjacent and same-document hits are reported separately.

Unlike the scores further up this file, these are worth writing down: no LLM runs
at query time on the dense or hybrid paths, so the same set gives the same numbers
every run.

### What it measures, on 120 passages at k=10

| | named r@5 | named r@10 | named MRR | right doc | topical r@10 | topical MRR | median |
|---|---|---|---|---|---|---|---|
| dense (shipping) | 25.0% | 30.8% | 0.182 | 55.0% | **20.8%** | 0.085 | 3.35s |
| hybrid (RRF over both rankings) | 22.5% | 29.2% | 0.145 | 62.5% | 19.2% | 0.088 | 3.46s |
| filtered (words pick filing, vectors pick passage) | 25.0% | 36.7% | 0.192 | 65.0% | 17.5% | 0.084 | 3.25s |
| filtered + reranker | 40.0% | 45.0% | 0.278 | 66.7% | 20.0% | **0.104** | 5.63s |
| **contextual** | 57.5% | **70.0%** | **0.422** | 96.7% | 12.5% | 0.069 | **2.57s** |
| contextual + reranker | **62.5%** | 69.2% | 0.394 | **98.3%** | 15.0% | 0.087 | 4.53s |
| contextual + filtered + reranker | 58.3% | 67.5% | 0.396 | 93.3% | 16.7% | **0.104** | 5.01s |

### What that says

**One line of metadata beat every retrieval technique tried.** Embedding each
passage with a line naming its filing — company, ticker, form, fiscal year,
section, all of it already sitting in the filings table — takes named MRR from
0.182 to 0.422 and the right document from 55.0% to 96.7%. No LLM per chunk, no
second index, no extra query. It is also the fastest configuration measured, at
2.57s against the baseline's 3.35s, because it needs neither a lexical query nor
a second dense pass.

The reason is the failure the earlier rows were all circling. A stored passage
has no identity: "we may be unable to protect our intellectual property" is
nearly the same sentence, and so nearly the same vector, in every filing that
contains it. Hybrid retrieval, the lexical filter and the reranker were three
increasingly elaborate ways to recover an identity that had been discarded at
embedding time. Putting it back where it was lost costs less and works better.

**Two stages were made redundant by it, and the numbers say so plainly.** The
lexical filter existed to work out which company filed a document. Contextual
embedding does that better on its own — 96.7% against the filter's 65.0% — so
adding the filter back *lowers* the result to 93.3%. The elaborate pipeline
loses to the simple one.

**A reranker helps a weak retriever and hurts a strong one.** On the dense
baseline it was the largest single gain available (0.192 to 0.278). On top of
contextual embeddings it makes named questions worse, 0.422 to 0.394: recall@5
rises to 62.5% while recall@1 falls from 30.8% to 25.8%, which is a reranker
demoting correct top answers it was asked to re-judge. It is worth its 2s only
where retrieval is not already finding the answer.

**The cost falls exactly where the mechanism predicts.** Topical questions name
no company, so the context line adds an identity the question cannot use, and
dilutes the subject matter that is all it has to go on: recall@10 falls from
20.8% to 12.5%, the worst of any configuration. Every configuration that helps
topical questions contains the reranker, and none of them beats plain dense by
much (0.104 against 0.085).

### What should ship, on this evidence

- **Contextual embeddings, as the dense space.** Largest gain, lowest latency,
  and it retires two stages rather than adding one.
- **Not hybrid, and not the lexical filter.** Both were measured and both are
  subsumed. Keeping them would be keeping machinery for the story it tells
  rather than the work it does.
- **The reranker, conditionally.** It earns its place on topical questions and
  costs accuracy on named ones, which is a decision the system can already make:
  `chat.py` knows whether it resolved a company. Reranking when it did not, and
  skipping it when it did, is the configuration the table supports — and is
  itself the next thing to measure rather than assume.

Two caveats stay attached to all of the above. The labels are synthetic, and a
question written *from* a passage may reward document identity more than a real
user's question would — the topical column is the closer proxy for hard cases,
and it is the column contextual embedding hurts. And the production path often
passes a ticker already, which supplies the same identity by a different route;
the ticker-scoped case has not been measured, and it is the one that decides how
much of this gain survives contact with the real caller.

### Where the lexical query had to be measured too

The obvious lexical query does not work at either extreme, and both were measured
rather than guessed. ORing the words of a real question matches 294,793 of the
334,624 passages and takes 48 seconds to rank. ANDing them matches nothing, since
no passage contains every word of a sentence. Requiring only the query's *rarest*
words is the version that is both fast and selective, and rarity had to be
measured against this corpus rather than against English — `build_fts_stats.py`
finds "may" in 95.9% of passages and "product" in 80.3%. The resulting lexical
query runs in 0.02s against the dense side's 3.4s.

## Limitations

- Retrieval correctness is not deterministic, since an LLM translates the question.
  Exact match moves between runs when the model phrases a query slightly
  differently, which is why the scores are not recorded here.
- Recall alone can flatter a bad answer, as the threshold failure above shows, so
  it is never read on its own.
- Groundedness only checks the cleanly verifiable claim types (money, counts, NCT ids, statuses); free prose is not scored.
- Retrieval correctness only applies to structured questions, where independent groundtruth exists. Semantic search has no exact ground-truth set, so it is checked only through groundedness.
- The question set is small and fixed on purpose. Adding more is easy.
- The retrieval labels are synthetic. A model wrote each question from the passage
  it is then asked to find, so the set measures whether a passage is findable from
  a question derived from it — not whether real questions find it. It is a
  relative instrument: good for comparing two retrievers on identical input, not
  for claiming an absolute quality of search.
- 120 passages is few. At a recall of about 30% the sampling error is roughly
  ±8 points, so differences smaller than that are noise. The gap between dense and
  hybrid on *right document* (7.5 points) sits right at that edge and should be
  read as suggestive, not settled; the MRR difference is larger relative to its
  own scale.
- "Exact" is strict by construction. Chunks overlap by 300 characters, so the
  passage next door often contains the same sentence, and the adjacent and
  document columns exist because scoring those as plain misses would understate
  every retriever equally but misleadingly.
