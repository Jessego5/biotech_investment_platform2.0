"""
Reorder retrieved passages by reading them.

Retrieval ranks by similarity between a question and a passage, which is a
proxy for "answers this question" and sometimes a bad one: a passage can be
about exactly the right subject and still not contain the answer. A reranker
looks at the candidates against the question and puts the ones that actually
answer it first. It is the standard second stage, and it earns its place only
if it moves the number in eval_retrieval.py — which is why it is a separate
module that the eval can switch on and off rather than something wired into the
search.

There is no cross-encoder here. The usual choice is a small local model, and
that means torch, which is two gigabytes to make a reordering decision that this
project already has an LLM on hand for. So this is a listwise LLM reranker: all
candidates in one call, scored together, which lets the model compare them
against each other rather than judge each in isolation.

Two things it deliberately does NOT do:

  - It does not invent a score for the answer to stand on. The cosine similarity
    stays on every hit, untouched, and the relevance floor still applies to it.
    The reranker only changes ORDER.

  - It does not decide what the answer reads. Candidates are truncated to keep
    the ranking call cheap, and that truncation is why this is kept apart from
    the passage the model answers from — that one arrives whole. Confusing the
    two is exactly the bug that made the interface claim the model had read a
    3,000 character passage it had seen a fifth of.
"""

import json
import os

RERANK_MODEL = "gpt-4o-mini"

# How many retrieved passages to consider. Reranking is only useful if the right
# passage is somewhere in the candidates, so this wants to be comfortably deeper
# than the number kept — but every candidate is tokens in the prompt.
CANDIDATES = 20

# How much of each passage the ranker sees. Enough to tell whether a passage
# answers the question, not enough to be what anyone answers from.
SNIPPET_CHARS = 700

SYSTEM = (
    "You rank passages from company annual reports by how well each ANSWERS a "
    "question. Answering is not the same as being on the same subject: a "
    "passage that discusses the topic without containing the answer ranks below "
    "one that contains it.\n\n"
    "Score every passage from 0 to 10. Return JSON: "
    '{"scores": [{"i": <passage number>, "score": <0-10>}, ...]} '
    "with one entry per passage given, and nothing else."
)


def _client():
    from openai import OpenAI
    return OpenAI()


def _prompt(query, hits):
    parts = [f"Question: {query}", ""]
    for i, h in enumerate(hits, 1):
        head = f"[{i}] {h.get('ticker','?')} FY{h.get('fiscal_year','?')} {h.get('section','')}"
        parts.append(f"{head}\n{(h.get('text') or '')[:SNIPPET_CHARS]}")
    return "\n\n".join(parts)


def rerank(query, hits, keep=6, candidates=CANDIDATES):
    """
    Reorder hits by judged relevance, returning the best `keep`.

    Falls back to the order it was given if there is no API key or the call
    fails. A reranker that cannot run should cost the ranking nothing, not take
    the search down with it — retrieval already returned usable results.
    """
    pool = hits[:candidates]
    if len(pool) < 2 or not os.environ.get("OPENAI_API_KEY"):
        return hits[:keep]

    try:
        resp = _client().chat.completions.create(
            model=RERANK_MODEL,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": _prompt(query, pool)}],
        )
        scored = json.loads(resp.choices[0].message.content).get("scores", [])
    except Exception:
        return hits[:keep]

    judged = {}
    for row in scored:
        try:
            i = int(row["i"]) - 1
            if 0 <= i < len(pool):
                judged[i] = float(row["score"])
        except (KeyError, TypeError, ValueError):
            continue
    if not judged:
        return hits[:keep]

    # A passage the model skipped keeps its retrieved position rather than being
    # dropped: silence from the ranker is not evidence against a passage. The
    # retrieval rank breaks ties, so an unjudged candidate never overtakes a
    # judged one on equal scores.
    order = sorted(range(len(pool)),
                   key=lambda i: (-judged.get(i, -1.0), i))
    out = []
    for i in order:
        hit = dict(pool[i])
        hit["rerank"] = judged.get(i)
        out.append(hit)
    return out[:keep]
