"""
This is the grounded chat. The model never answers from its own memory. First it
turns the question into a structured query plan, then we run that plan against the
real database, and then the model phrases an answer using only the rows we got
back. Because the lookup is a database query and not a vector search, the results
are exact and complete. If nothing relevant comes back, the honest answer is that
there is no data on that, not a made up one. It uses OpenAI and needs
OPENAI_API_KEY. Without the key the chat is simply off.
"""

import json
import os

from .retrieval import query_companies, company_facts
from .semantic import semantic_search

CHAT_MODEL = "gpt-4o-mini"

# Step 1 prompt: turn the question into a query plan. the model does NOT answer
# here and knows no company data, it only picks a query.
PLAN_SYSTEM = (
    "You translate a question about a biotech company database into a structured "
    "query plan. You do NOT answer the question and you know no company data "
    "yourself. Return ONLY JSON of this shape:\n"
    '{\n'
    '  "intent": "filter" | "company" | "search" | "greeting" | "refuse",\n'
    '  "reason": string,               // if refuse, a short why\n'
    '  "ticker": string | null,        // if the question is about ONE company\n'
    '  "search_query": string | null,  // for intent=search: a concise search phrase\n'
    '  "filters": {                    // for intent=filter; all optional\n'
    '     "min_rd": number|null,       // minimum R&D expense in DOLLARS\n'
    '     "min_cash": number|null,     // minimum cash in DOLLARS\n'
    '     "min_active_trials": integer|null,\n'
    '     "has_phase3": boolean|null,  // true = has a Phase 3+ program\n'
    '     "sector": string|null,       // one of: Biologics, Pharma preparations, Bio research\n'
    '     "min_runway": number|null    // minimum cash / annual R&D ratio\n'
    '  },\n'
    '  "sort_by": "rd"|"cash"|"active_trials"|"total_trials"|"runway"|null,\n'
    '  "limit": integer|null           // for "top N" / "most" questions\n'
    '}\n'
    "Convert money to raw dollars (\"$1 billion\" becomes 1000000000). "
    "If the message is a greeting or small talk (hi, hello, how are you), or asks "
    "what you can do or how this works, use intent=greeting. "
    "If the question is about one named company, use intent=company and put its "
    "ticker (or the name) in ticker. "
    "If the question is about trial CONTENT, a disease or condition, a drug, a "
    "therapy or mechanism (e.g. CAR-T, oncology, a specific mutation), or asks "
    "what trials study or test something, use intent=search and put a concise "
    "search phrase in search_query. There is no structured field for those, so "
    "they are answered by semantic search over trial descriptions. Do NOT map "
    "them to sector: sector is only one of exactly Biologics, Pharma "
    "preparations, or Bio research. "
    "If the question asks to predict the future, give buy/sell or investment "
    "advice, or asks anything neither the structured data nor the trial text can "
    "answer, use intent=refuse. "
    "Data available per company: name, sector (those three labels only), trial "
    "counts by phase and status, active and terminated counts, R&D expense, cash, "
    "and a cash/R&D runway proxy."
)

# Step 2 prompt: answer strictly from the retrieved rows.
ANSWER_SYSTEM = (
    "You answer a question using ONLY the retrieved rows given to you. STRICT "
    "RULES: use only that data, never add outside knowledge, never invent numbers, "
    "never give buy/sell advice or predictions. If the rows do not answer the "
    "question, say you don't have data on that. Be concise and factual."
)

# canned reply for greetings and "what can you do", friendlier than a refusal
# and deterministic (no LLM call), so it always states the same purpose.
GREETING = (
    "Hi. I answer questions about this biotech database, using only the real "
    "pipeline and financial data stored here. Try asking things like: "
    "\"Which companies have a Phase 3 trial and over 2x cash runway?\", "
    "\"Who has the most clinical trials?\", or \"What is Moderna's cash position?\""
)


def _client():
    from openai import OpenAI
    return OpenAI()  


def _money(entry):
    # missing figures read as "n/a" rather than a fake zero
    if not entry:
        return "n/a"
    # show the value in millions with its fiscal year
    return f"${round(entry['value'] / 1e6)}M (FY{entry['fiscal_year']})"


def _plan(question):
    # ask the model to translate the question into a JSON query plan
    resp = _client().chat.completions.create(
        model=CHAT_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": PLAN_SYSTEM},
                  {"role": "user", "content": question}],
    )
    # parse the JSON it returned back into a dict
    return json.loads(resp.choices[0].message.content)


def _retrieve(plan, db):
    """Run the plan against the DB. Returns (facts_text, sources, retrieved_count)."""
    intent = plan.get("intent")

    # one named company: pull its full grounded facts and lay them out
    if intent == "company":
        ticker = (plan.get("ticker") or "").upper()
        facts = company_facts(db, ticker) if ticker else None
        # no ticker or not in the DB means nothing to retrieve
        if not facts:
            return "", [], 0
        a = facts["assessment"]
        # start with the company header and its pipeline signal
        lines = [
            f"{facts['ticker']}: {facts['name']} (sector: {facts['sector']})",
            f"Pipeline signal: {a['pipeline_signal']['label']}",
        ]
        # add the pipeline evidence, then the financial signal and its evidence
        lines += [f"  - {e}" for e in a["pipeline_signal"]["evidence"]]
        lines.append(f"Financial signal: {a['financial_signal']['label']}")
        lines += [f"  - {e}" for e in a["financial_signal"]["evidence"]]
        return "\n".join(lines), [facts["ticker"]], 1

    # filter intent: run the structured query with whatever filters the plan gave
    if intent == "filter":
        f = plan.get("filters") or {}
        rows = query_companies(
            db,
            min_rd=f.get("min_rd"), min_cash=f.get("min_cash"),
            has_phase3=f.get("has_phase3"),
            min_active_trials=f.get("min_active_trials"),
            sector=f.get("sector"), min_runway=f.get("min_runway"),
            sort_by=plan.get("sort_by"), limit=None,
        )
        total = len(rows)
        # cap how many rows we feed the model, defaulting to 25
        shown = rows[:(plan.get("limit") or 25)]
        # the header states the full match count, even if we only show some
        header = f"Total companies matching: {total}"
        if total > len(shown):
            header += f" (showing the first {len(shown)})"
        lines = [header, ""]
        # write one compact line per company with its key numbers
        for r in shown:
            lines.append(
                f"{r['ticker']}: {r['name']} | sector={r['sector']} | "
                f"trials={r['total_trials']} active={r['active_trials']} "
                f"phase3={'yes' if r['has_phase3'] else 'no'} | "
                f"R&D={_money(r['rd_expense'])} cash={_money(r['cash'])} "
                f"runway={r['runway'] if r['runway'] is not None else 'n/a'}"
            )
        return "\n".join(lines), [r["ticker"] for r in shown], total

    # search intent: semantic search over the trial descriptions
    if intent == "search":
        query = plan.get("search_query") or ""
        trials = semantic_search(query, k=8) if query else []
        # nothing matched, so retrieve nothing
        if not trials:
            return "", [], 0
        lines = ["Trials whose descriptions best match the question:", ""]
        # one block per matching trial, with a short snippet of its summary
        for t in trials:
            # collapse newlines and cap the snippet length
            snippet = (t["summary"] or "").replace("\n", " ")[:320]
            lines.append(
                f"{t['nct_id']} ({t['ticker']}): {t['title']} | {t['phase']} | "
                f"{t['status']}\n  {snippet}"
            )
        # unique tickers in their original order, for the source chips
        sources = list(dict.fromkeys(t["ticker"] for t in trials if t["ticker"]))
        return "\n".join(lines), sources, len(trials)

    # any other intent retrieves nothing
    return "", [], 0


def _answer(question, facts_text):
    # build the prompt, handing the model only the retrieved rows to work from
    prompt = (
        f"Question: {question}\n\n"
        f"Retrieved rows (the ONLY data you may use):\n"
        f"{facts_text if facts_text.strip() else '(no rows matched)'}\n\n"
        "Answer using only these rows."
    )
    resp = _client().chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "system", "content": ANSWER_SYSTEM},
                  {"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


def answer_question(question, db):
    """Full flow: plan -> retrieve real rows -> grounded answer + sources."""
    # no OpenAI key means the chat is simply off, so say so plainly
    if not os.environ.get("OPENAI_API_KEY"):
        return {"answer": "The chat needs an OpenAI API key. Set OPENAI_API_KEY in "
                          "backend/.env (the rest of the app works without it).",
                "sources": [], "unavailable": True}

    # step 1: turn the question into a query plan, bailing out if that fails
    try:
        plan = _plan(question)
    except Exception as e:
        return {"answer": f"Sorry, I couldn't process that question ({e}).",
                "sources": []}

    # a greeting gets the canned welcome reply instead of a data lookup
    if plan.get("intent") == "greeting":
        return {"answer": GREETING, "sources": [], "plan": plan}

    # a refusal politely declines and points at what the data can actually answer
    if plan.get("intent") == "refuse":
        reason = plan.get("reason") or "That is outside what this data can answer."
        return {"answer": f"I can't answer that. {reason} I only report the real "
                          "pipeline and financial data in the database, so try asking "
                          "about trials by phase, R&D, cash, runway, or filtering "
                          "companies.",
                "sources": [], "plan": plan}

    # step 2: run the plan against the real DB to get the rows
    facts_text, sources, count = _retrieve(plan, db)
    # step 3: have the model phrase an answer from only those rows
    answer = _answer(question, facts_text)
    # "retrieved" is the exact text the answer was allowed to use. the eval
    # suite checks every claim in the answer against it (groundedness).
    return {"answer": answer, "sources": sources, "match_count": count,
            "plan": plan, "retrieved": facts_text}
