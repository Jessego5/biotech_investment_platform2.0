"""
This is the retrieval evaluation for the two paths that search text instead of
computing a figure. evaluate.py already measures the structured side, computing
the true set of companies from the raw rows and checking the system's set against
it, while the text side had nothing equivalent, so the component that is hardest
to get right, ranking 334,624 filing passages, was also the one with no number
attached. Nobody has labelled this corpus and labelling it by hand is not on, so
the labels are made the standard way for a known-item test: take a passage out of
the corpus, ask a model to write the question that passage answers, then throw
the question at the whole corpus and see whether that exact passage comes back,
which makes the passage the answer by construction and means no human has to
judge relevance. Three things keep the number honest rather than flattering. The
query set is generated once and stored in eval_retrieval_set.json, because a
retrieval change is only worth a number if the before and the after were asked
the same questions and a set regenerated per run would hide a regression inside
its own sampling noise. Each passage gets two questions, a named one mentioning
the company, which is how people really ask, and a topical one that deliberately
does not, leaving the searcher to find one passage in 334,624 on subject matter
alone; they measure different things and are reported apart, because a system
that can only find a passage when handed the ticker is doing much less work than
one number would suggest. And retrieval runs with the relevance floor off, the
floor being applied afterwards in the report, because otherwise a passage that
ranked first and was then cut is indistinguishable from one that never ranked at
all and those two failures have opposite fixes. Neighbouring chunks overlap by
300 characters and usually continue the same argument, so landing on the chunk
next door is not the same kind of miss as landing in another company's filing,
and the report separates exact, adjacent and same-document hits rather than
calling everything but an exact match a failure. Build the set once with python
eval_retrieval.py --build, which costs a few cents, then run python
eval_retrieval.py as often as you like for free.
"""

import argparse
import json
import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from sqlalchemy import text

from app.database import SessionLocal
from app import rerank as rerank_mod
from app.semantic import (search_filings, search_filings_hybrid,
                          search_filings_filtered, MIN_FILING_SCORE)

QUESTION_MODEL = "gpt-4o-mini"
SET_PATH = os.path.join(os.path.dirname(__file__), "eval_retrieval_set.json")

# How many passages to draw from each section. Weighted towards the sections a
# reader actually asks about rather than towards how many chunks each has: risk
# factors are three quarters of the corpus but not three quarters of the
# questions, and intellectual property is 4% of the corpus and the subject of
# the product's own worked example.
SAMPLE_PLAN = {"risk_factors": 50, "mdna": 35, "intellectual_property": 35}

# Short chunks are section headings, page furniture and tables of contents.
# There is no specific question to ask of them, so they are not sampled.
MIN_CHUNK_CHARS = 1500

# The seed is fixed so that rebuilding the set draws the same passages. It only
# matters if the set is ever rebuilt, which is exactly when it matters most.
SAMPLE_SEED = 0.42

# Questions with no answer anywhere in the corpus. The floor is supposed to send
# these back empty, and the measured distributions that set it at 0.30 live in a
# comment in semantic.py, this turns that comment into a test.
OFF_TOPIC = [
    "the weather forecast tomorrow",
    "time travel and wormholes",
    "best pizza recipe",
    "how to train for a marathon",
    "who won the world cup in 1998",
    "javascript array sort performance",
]

# The other half of the same test. A floor high enough to refuse everything
# would score perfectly on the list above, so these have to keep coming back.
ON_TOPIC = [
    "patent protection for our lead product",
    "competition from biosimilars",
    "manufacturing capacity constraints",
    "reliance on third party clinical trial sites",
    "risks from reimbursement and payer coverage",
    "dependence on a single approved product for revenue",
]

BUILD_SYSTEM = (
    "You are given one passage from a public company's annual report. Write the "
    "questions a reader would ask that THIS passage answers.\n\n"
    "Return JSON with exactly two keys:\n"
    '  "named"   - a question that names the company, as a person would ask it.\n'
    '  "topical" - the same information need with the company NOT named and no '
    "product or trade name that would identify it, so it reads as a question "
    "about the subject rather than about the filer.\n\n"
    "Rules: one sentence each, under 25 words. Ask about what is specific to "
    "this passage, not what any annual report would say. Do not copy a sentence "
    "from the passage verbatim. If the passage is a heading, a table of "
    'contents, or boilerplate with nothing specific to ask, return {"named": '
    'null, "topical": null}.'
)


def _client():
    from openai import OpenAI
    return OpenAI()


# - building the set

def _sample_chunks(db):
    """
    Draw passages per section, deterministically.

    setseed makes random() repeatable inside this session, so a rebuild picks the
    same passages and any change in the score is a change in the retriever rather
    than a change in what it was asked.
    """
    db.execute(text("select setseed(:s)"), {"s": SAMPLE_SEED})
    rows = []
    for section, n in SAMPLE_PLAN.items():
        got = db.execute(text("""
            select c.id, c.section, c.ordinal, c.text,
                   f.id as filing_id, f.company_ticker, f.fiscal_year, f.form, f.filed,
                   co.name as company_name
            from filing_chunks c
            join filings f on c.filing_id = f.id
            left join companies co on co.ticker = f.company_ticker
            where c.section = :section
              and length(c.text) >= :minlen
              and c.embedding is not null
            order by random()
            limit :n
        """), {"section": section, "minlen": MIN_CHUNK_CHARS, "n": n}).mappings().all()
        rows += [dict(r) for r in got]
    return rows


def _write_questions(chunk):
    """Ask for the two questions this passage answers. None means unusable."""
    passage = chunk["text"][:3000]
    header = (f"{chunk['company_name'] or chunk['company_ticker']} "
              f"({chunk['company_ticker']}) · {chunk['form']} · "
              f"FY{chunk['fiscal_year']} · {chunk['section']}")
    resp = _client().chat.completions.create(
        model=QUESTION_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": BUILD_SYSTEM},
                  {"role": "user", "content": f"{header}\n\n{passage}"}],
    )
    try:
        out = json.loads(resp.choices[0].message.content)
    except (json.JSONDecodeError, TypeError):
        return None, None
    return out.get("named"), out.get("topical")


def build_set():
    db = SessionLocal()
    try:
        chunks = _sample_chunks(db)
    finally:
        db.close()

    print(f"sampled {len(chunks)} passages; writing questions with {QUESTION_MODEL}")
    cases, skipped = [], 0
    for i, c in enumerate(chunks, 1):
        named, topical = _write_questions(c)
        if not named or not topical:
            skipped += 1
        else:
            cases.append({
                "chunk_id": c["id"],
                "filing_id": c["filing_id"],
                "ordinal": c["ordinal"],
                "section": c["section"],
                "ticker": c["company_ticker"],
                "fiscal_year": c["fiscal_year"],
                "named": named.strip(),
                "topical": topical.strip(),
            })
        if i % 20 == 0:
            print(f"  {i}/{len(chunks)}")

    payload = {
        "built": time.strftime("%Y-%m-%d"),
        "model": QUESTION_MODEL,
        "seed": SAMPLE_SEED,
        "plan": SAMPLE_PLAN,
        "cases": cases,
        "off_topic": OFF_TOPIC,
        "on_topic": ON_TOPIC,
    }
    with open(SET_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    print(f"wrote {len(cases)} cases to {SET_PATH} ({skipped} passages had no "
          f"specific question to ask)")


# - running it

def _rank_of(hits, case):
    """
    Where the target passage came back, and how close the near misses were.

    Returns (exact_rank, adjacent_rank, document_rank), each 1-based or None.
    Adjacent means the chunk either side of the target in the same section: the
    300-character overlap means those often carry the same sentence, so counting
    them as a plain miss overstates the failure.
    """
    exact = adjacent = document = None
    for i, h in enumerate(hits, 1):
        same_doc = h.get("filing_id") == case["filing_id"]
        if h["chunk_id"] == case["chunk_id"] and exact is None:
            exact = i
        if same_doc:
            if document is None:
                document = i
            if (adjacent is None and h.get("section") == case["section"]
                    and h.get("ordinal") is not None
                    and abs(h["ordinal"] - case["ordinal"]) <= 1):
                adjacent = i
    return exact, adjacent, document


def _at(ranks, k):
    """Share of cases whose target came back at rank k or better."""
    if not ranks:
        return 0.0
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)


def _mrr(ranks):
    if not ranks:
        return 0.0
    return sum((1.0 / r) if r else 0.0 for r in ranks) / len(ranks)


def run_flavour(cases, flavour, k, retriever):
    """Search once per case and collect where the target landed."""
    exact, adjacent, document, floored_out, latencies = [], [], [], 0, []
    for i, case in enumerate(cases, 1):
        t0 = time.time()
        hits = retriever(case[flavour], k)
        latencies.append(time.time() - t0)
        e, a, d = _rank_of(hits, case)
        exact.append(e)
        adjacent.append(a)
        document.append(d)
        # would the production floor have thrown the target away after finding it?
        if e is not None and hits[e - 1]["score"] < MIN_FILING_SCORE:
            floored_out += 1
        if i % 25 == 0:
            print(f"    {flavour}: {i}/{len(cases)}")
    return {"exact": exact, "adjacent": adjacent, "document": document,
            "floored_out": floored_out, "latencies": latencies}


def dense_retriever(query, k):
    """The retriever as it ships today: one dense vector, cosine, top k."""
    return search_filings(query, k=k, all_years=True, min_score=0.0)


def hybrid_retriever(query, k):
    """Dense and lexical rankings fused by RRF. Same floor, same shape."""
    return search_filings_hybrid(query, k=k, all_years=True, min_score=0.0)


def hybrid_rerank_retriever(query, k):
    """
    Hybrid, then read the candidates and reorder them.

    The pool is deliberately deeper than what is kept: a reranker can only
    promote a passage that retrieval already found, so the question it answers
    is whether the right passage was in the pool and merely ranked badly.
    """
    pool = search_filings_hybrid(query, k=max(k, rerank_mod.CANDIDATES),
                                 all_years=True, min_score=0.0)
    return rerank_mod.rerank(query, pool, keep=k)


def filtered_retriever(query, k):
    """Words choose the filing, vectors choose the passage within it."""
    return search_filings_filtered(query, k=k, all_years=True, min_score=0.0)


def filtered_rerank_retriever(query, k):
    """
    The best retriever measured so far, then read the candidates and reorder.

    Stacked on `filtered` rather than on `hybrid` on purpose: a reranker can only
    promote what retrieval already found, so it belongs on top of whichever
    retriever puts the right passage in the pool most often, not on top of the
    one that lost.
    """
    pool = search_filings_filtered(query, k=max(k, rerank_mod.CANDIDATES),
                                   all_years=True, min_score=0.0)
    return rerank_mod.rerank(query, pool, keep=k)


def contextual_retriever(query, k):
    """Dense, but against the vectors that were given their document's identity.

    Paired with `dense` and nothing else: the only difference between the two is
    which column is searched, so any gap between them is the contextual
    embedding and not a second change riding along with it.
    """
    return search_filings(query, k=k, all_years=True, min_score=0.0,
                          use_context=True)


def ctx_filtered_rerank_retriever(query, k):
    """The whole stack: contextual vectors, lexical filing filter, reranker."""
    pool = search_filings_filtered(query, k=max(k, rerank_mod.CANDIDATES),
                                   all_years=True, min_score=0.0,
                                   use_context=True)
    return rerank_mod.rerank(query, pool, keep=k)


def contextual_rerank_retriever(query, k):
    """
    Contextual vectors, then the reranker, and no lexical filter.

    The configuration the measurements point at rather than one that was planned.
    Contextual embeddings put the right document in the top ten 96.7% of the time
    on their own, which is more than the lexical filter managed and leaves it
    nothing to add; adding it back measured worse. The reranker is kept because
    it is the one stage that helped topical questions, which are exactly the ones
    the context line does not help.
    """
    pool = search_filings(query, k=max(k, rerank_mod.CANDIDATES), all_years=True,
                          min_score=0.0, use_context=True)
    return rerank_mod.rerank(query, pool, keep=k)


RETRIEVERS = {"dense": dense_retriever,
              "contextual": contextual_retriever,
              "contextual+rerank": contextual_rerank_retriever,
              "ctx+filtered+rerank": ctx_filtered_rerank_retriever,
              "filtered": filtered_retriever,
              "filtered+rerank": filtered_rerank_retriever,
              "hybrid": hybrid_retriever,
              "hybrid+rerank": hybrid_rerank_retriever}


def run_abstention(queries, expect_hits, retriever, k):
    """How often the floor gets the on/off topic call right."""
    wrong, detail = 0, []
    for q in queries:
        # one search, then both readings taken from it. Searching twice to get
        # the top score as well as the surviving hits doubled the cost of this
        # section for nothing.
        raw = retriever(q, k)
        hits = [h for h in raw if h["score"] >= MIN_FILING_SCORE]
        ok = bool(hits) == expect_hits
        if not ok:
            wrong += 1
        detail.append((q, len(hits), max((h["score"] for h in raw), default=0.0), ok))
    return wrong, detail


def report(name, res, n):
    ex, ad, doc = res["exact"], res["adjacent"], res["document"]
    print(f"\n  {name}")
    print(f"    recall@1  {_at(ex,1):6.1%}    recall@5  {_at(ex,5):6.1%}"
          f"    recall@10 {_at(ex,10):6.1%}    MRR {_mrr(ex):.3f}")
    print(f"    adjacent chunk in top 10 ....... {_at(ad,10):6.1%}")
    print(f"    right document in top 10 ....... {_at(doc,10):6.1%}")
    print(f"    found but cut by the floor ..... {res['floored_out']}/{n}")
    lat = res["latencies"]
    print(f"    median latency ................. {sorted(lat)[len(lat)//2]:.2f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true",
                    help="regenerate the stored question set (costs an API call per passage)")
    ap.add_argument("--retriever", default="dense", choices=sorted(RETRIEVERS))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--limit", type=int, default=None,
                    help="run only the first N cases, for a quick check")
    args = ap.parse_args()

    if args.build:
        build_set()
        return

    if not os.path.exists(SET_PATH):
        sys.exit(f"No question set at {SET_PATH}. Run with --build first.")
    payload = json.load(open(SET_PATH, encoding="utf-8"))
    cases = payload["cases"][:args.limit] if args.limit else payload["cases"]
    retriever = RETRIEVERS[args.retriever]

    print(f"Retrieval eval · retriever={args.retriever} · k={args.k} · "
          f"{len(cases)} passages · set built {payload['built']}")
    print("Known-item: the passage each question was written from must come back.")

    results = {}
    for flavour in ("named", "topical"):
        results[flavour] = run_flavour(cases, flavour, args.k, retriever)
        report(f"{flavour} queries", results[flavour], len(cases))

    print("\n  abstention (production floor applied)")
    off_wrong, off_detail = run_abstention(payload["off_topic"], False, retriever, args.k)
    on_wrong, on_detail = run_abstention(payload["on_topic"], True, retriever, args.k)
    print(f"    off-topic answered anyway ...... {off_wrong}/{len(off_detail)}")
    print(f"    on-topic refused wrongly ....... {on_wrong}/{len(on_detail)}")
    for q, n_hits, top, ok in off_detail + on_detail:
        print(f"      {'ok ' if ok else 'BAD'} top={top:.3f} hits={n_hits:2d}  {q}")


if __name__ == "__main__":
    main()
