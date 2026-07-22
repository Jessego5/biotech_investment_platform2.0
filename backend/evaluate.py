"""
This is the evaluation suite for the grounded system. It runs three checkable
metrics over a fixed question set and prints a report. Groundedness asks whether
every claim in an answer is supported by what was retrieved. Retrieval correctness
asks whether the system's set matches the true set computed straight from the
database, using precision, recall, and exact match. Refusal asks whether it
declines ungroundable questions instead of making something up. The ground truth
comes directly from the real database, independent of the system. See EVALUATION.md
for the methodology. Run it with python evaluate.py, which needs OPENAI_API_KEY in
backend/.env.
"""

import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from app.database import SessionLocal
from app.chat import answer_question
from app.retrieval import query_companies
import eval_questions as Q


# - claim extraction for groundedness. We check the claim types that are cleanly
# verifiable against retrieved text: money figures, counts (a number tied to a
# data noun), trial NCT ids, and trial statuses.
STATUS_TOKENS = ["RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION",
                 "COMPLETED", "TERMINATED", "WITHDRAWN", "SUSPENDED", "NOT_YET_RECRUITING"]
COUNT_RE = re.compile(r"\b(\d+)\s+(trials?|active|terminated|programs?|companies|studies)", re.I)


def _to_millions(numstr, unit):
    # take out the commas so the number string can become a float
    n = float(numstr.replace(",", ""))
    # get the unit in lowercase so we can compare it
    u = (unit or "").lower()
    # a billion is 1000 millions
    if u in ("billion", "b"):
        return n * 1000
    # a million is already counted in millions
    if u in ("million", "m"):
        return n
    # a thousand is a tiny fraction of a million
    if u in ("thousand", "k"):
        return n / 1000
    # no unit means the number is a raw dollar amount, so convert it to millions
    return n / 1e6


def _money_values(text):
    """All money figures in the text, as values in $millions (deduped)."""
    vals = []
    # 1. dollar amounts written with a $ sign, with or without a unit word
    for m in re.finditer(r"\$\s?([\d,]+(?:\.\d+)?)\s*(billion|million|thousand|b|m|k)?", text, re.I):
        vals.append(_to_millions(m.group(1), m.group(2)))
    # 2. amounts written as "N billion" or "N million" with no $ in front
    for m in re.finditer(r"\b([\d,]+(?:\.\d+)?)\s*(billion|million)\b", text, re.I):
        vals.append(_to_millions(m.group(1), m.group(2)))
    # 3. big raw numbers with commas (millions or more) and no unit word
    for m in re.finditer(r"\b(\d{1,3}(?:,\d{3}){2,})\b", text):
        vals.append(_to_millions(m.group(1), None))
    # dedup by the rounded value so "$7.675 billion" and "7,675,000,000" only count once
    seen, out = set(), []
    for v in vals:
        # round to the nearest tenth of a million to use as the key
        key = round(v, 1)
        # only keep this value if we have not seen the rounded key before
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _money_supported(v, retrieved_vals, tol=0.03):
    return any(abs(v - rv) <= tol * max(v, rv, 1.0) for rv in retrieved_vals)


def extract_claims(answer, retrieved):
    """Return a list of (type, text, supported) for each checkable claim."""
    claims = []
    # pull all the money figures out of the retrieved text to compare against
    rvals = _money_values(retrieved)
    # lowercase the retrieved text once so the status checks are case insensitive
    r_low = retrieved.lower()

    # money claims: every dollar figure in the answer should match a retrieved one
    for v in _money_values(answer):
        # format the figure for the report, in millions or billions
        disp = f"${v:.0f}M" if v < 1000 else f"${v/1000:.2f}B"
        claims.append(("money", disp, _money_supported(v, rvals)))

    # count claims: a number tied to a data noun, like "76 trials"
    for m in COUNT_RE.finditer(answer):
        # look at the words right before the number
        pre = answer[max(0, m.start() - 16):m.start()].lower()
        # skip it if the number is the question's own threshold ("more than 30 active"),
        # since that is a filter cutoff repeated back and not a data claim
        if any(w in pre for w in ("more than", "over ", "at least", "fewer than",
                                  "less than", "greater than", "than ", "under ")):
            continue
        num, noun = m.group(1), m.group(2)
        # the count is supported if that exact number shows up in the retrieved text
        supported = re.search(r"(?<!\d)" + re.escape(num) + r"(?!\d)", retrieved) is not None
        claims.append(("count", f"{num} {noun}", supported))

    # trial claims: each NCT id in the answer should appear in the retrieved rows
    for nct in re.findall(r"NCT\d+", answer):
        claims.append(("trial", nct, nct in retrieved))

    # status claims: a trial status word in the answer should appear in retrieved
    for st in STATUS_TOKENS:
        # the stored statuses use underscores, so also try the spaced out version
        spaced = st.replace("_", " ").lower()
        if st.lower() in answer.lower() or spaced in answer.lower():
            claims.append(("status", st, st.lower() in r_low or spaced in r_low))

    return claims


# - Dimension 1: groundedness
def run_groundedness(db):
    print("\n" + "=" * 70)
    print("DIMENSION 1: GROUNDEDNESS (are the answer's claims in the retrieved data?)")
    print("=" * 70)
    total, supported = 0, 0
    # go through each groundedness test question
    for q in Q.GROUNDEDNESS:
        # ask the system, which gives back its answer and what it retrieved
        r = answer_question(q, db)
        # break the answer into checkable claims and mark which ones are supported
        claims = extract_claims(r.get("answer", ""), r.get("retrieved", ""))
        n = len(claims)
        # count how many of the claims were supported by the retrieved data
        s = sum(1 for c in claims if c[2])
        total += n
        supported += s
        rate = f"{s}/{n}" if n else "no checkable claims"
        print(f"\n  Q: {q}")
        print(f"     claims supported: {rate}")
        # print out any unsupported claim, which is a possible hallucination
        for typ, txt, ok in claims:
            if not ok:
                print(f"     UNSUPPORTED [{typ}]: {txt}   <-- possible hallucination")
    # the overall rate is the supported claims out of all the claims
    grounded = supported / total if total else 1.0
    print(f"\n  >> Groundedness rate: {supported}/{total} = {grounded:.1%}")
    return grounded


# - Dimension 2: retrieval correctness vs independent DB ground truth
def run_structured(db):
    print("\n" + "=" * 70)
    print("DIMENSION 2: RETRIEVAL CORRECTNESS (system set vs independent DB truth)")
    print("=" * 70)
    precs, recs, exacts = [], [], []
    # go through each structured test question
    for tc in Q.STRUCTURED:
        # the correct set is computed straight from the database, on its own
        truth = tc["truth"](db)
        # ask the system the same question and grab the query plan it made
        r = answer_question(tc["question"], db)
        plan = r.get("plan") or {}
        # if the system chose to filter, run those same filters to get its set
        if plan.get("intent") == "filter":
            f = plan.get("filters") or {}
            got = query_companies(
                db, min_rd=f.get("min_rd"), min_cash=f.get("min_cash"),
                has_phase3=f.get("has_phase3"), min_active_trials=f.get("min_active_trials"),
                sector=f.get("sector"), min_runway=f.get("min_runway"),
                sort_by=plan.get("sort_by"), limit=None)
            system = {x["ticker"] for x in got}
        # if it did not choose to filter, treat its set as empty
        else:
            system = set()

        # true positives are the companies in both the system set and the truth set
        tp = len(system & truth)
        # precision is how many of the system's picks were actually correct
        prec = (tp / len(system)) if system else (1.0 if not truth else 0.0)
        # recall is how many of the true companies the system managed to find
        rec = (tp / len(truth)) if truth else 1.0
        # exact match means the two sets are identical
        exact = system == truth
        precs.append(prec); recs.append(rec); exacts.append(exact)

        print(f"\n  Q: {tc['question']}")
        print(f"     intent={plan.get('intent')}  truth={len(truth)}  system={len(system)}"
              f"  precision={prec:.2f}  recall={rec:.2f}  exact={'yes' if exact else 'no'}")
        # show a few companies the system missed or wrongly included
        missed = sorted(truth - system)[:6]
        extra = sorted(system - truth)[:6]
        if missed:
            print(f"     missed (in truth, not returned): {missed}")
        if extra:
            print(f"     extra (returned, not in truth):  {extra}")

    # average the three scores across all the questions
    mp = sum(precs) / len(precs)
    mr = sum(recs) / len(recs)
    em = sum(exacts) / len(exacts)
    print(f"\n  >> Mean precision: {mp:.1%}   Mean recall: {mr:.1%}   Exact-match: {em:.1%}")
    return mp, mr, em


# - Dimension 3: appropriate refusal
def run_refusal(db):
    print("\n" + "=" * 70)
    print("DIMENSION 3: APPROPRIATE REFUSAL (declines ungroundable questions)")
    print("=" * 70)
    refused = 0
    # go through each ungroundable question
    for q in Q.REFUSAL:
        # ask the system and check which intent it picked
        r = answer_question(q, db)
        intent = (r.get("plan") or {}).get("intent")
        # the right behavior is to refuse instead of making something up
        ok = intent == "refuse"
        refused += ok
        print(f"  [{'REFUSED' if ok else 'ANSWERED'}] intent={intent}  {q}")
    # the refusal rate is how many it declined out of the whole set
    rate = refused / len(Q.REFUSAL)
    print(f"\n  >> Refusal rate: {refused}/{len(Q.REFUSAL)} = {rate:.1%}")
    return rate


def main():
    # the chat needs an OpenAI key to run, so stop early if there is not one
    if not os.environ.get("OPENAI_API_KEY"):
        print("This eval calls the chat, so it needs OPENAI_API_KEY (set it in backend/.env).")
        return
    db = SessionLocal()
    try:
        # run all three dimensions and collect their scores
        g = run_groundedness(db)
        mp, mr, em = run_structured(db)
        rf = run_refusal(db)
    finally:
        db.close()

    print("\n" + "=" * 70)
    print("SUMMARY (honest numbers, including where it does poorly)")
    print("=" * 70)
    print(f"  Groundedness rate ................ {g:.1%}")
    print(f"  Retrieval mean precision ......... {mp:.1%}")
    print(f"  Retrieval mean recall ............ {mr:.1%}")
    print(f"  Retrieval exact-match ............ {em:.1%}")
    print(f"  Refusal rate (should be high) .... {rf:.1%}")
    print("\n  Ground truth was computed directly from the database, independently")
    print("  of the system under test. See EVALUATION.md for methodology.")


if __name__ == "__main__":
    main()
