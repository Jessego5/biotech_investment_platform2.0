"""
This is the grounded chat. The model never answers from its own memory. First it
turns the question into a structured query plan, then we run that plan against the
real database, and then the model phrases an answer using only the rows we got
back. Because the lookup is a database query and not a vector search, the results
are exact and complete. If nothing relevant comes back, the honest answer is that
there is no data on that, not a made up one. It uses OpenAI and needs
OPENAI_API_KEY. Without the key the chat is simply off.
"""

import datetime
import json
import os
import re

from .models import Company
from .exclusivity import protection_for
from .retrieval import query_companies, company_facts, upcoming_readouts
from .semantic import semantic_search, search_filings

CHAT_MODEL = "gpt-4o-mini"


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


# - tools
#
# The query plan used to be a fixed JSON menu: an intent enum and a filters
# object, and every question had to be expressible inside it. That menu went
# stale every time the schema grew, and it had: it offered three sector labels
# while the database held ten, so 124 medical-device companies could not be
# reached at all, and it knew nothing about patents, exclusivity, indications or
# readout dates.
#
# These are the same accessors the API already uses, exposed for the model to
# choose between. Every one of them returns a computed fact with its evidence.
# There is deliberately no "run this query" tool: choosing a tool is not
# inventing a number, but handing the model raw rows to do arithmetic on would
# be, and the whole app rests on that line.
MAX_ROUNDS = 3

TOOLS = [
    {"type": "function", "function": {
        "name": "filter_companies",
        "description": "Filter and rank companies by structured figures. Use for "
                       "'which companies', 'top N', 'most', 'more than X' questions.",
        "parameters": {"type": "object", "properties": {
            "min_rd": {"type": "number", "description": "minimum R&D expense in DOLLARS"},
            "min_cash": {"type": "number", "description": "minimum cash in DOLLARS"},
            "min_active_trials": {"type": "integer"},
            "has_phase3": {"type": "boolean"},
            "sector": {"type": "string", "description": "must be one of the labels listed in the system prompt"},
            "min_runway": {"type": "number", "description": "minimum years of runway"},
            "sort_by": {"type": "string", "enum": ["rd", "cash", "active_trials", "total_trials", "runway"]},
            "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "company_report",
        "description": "Everything held on ONE company: pipeline and financial "
                       "signals with the evidence behind each.",
        "parameters": {"type": "object", "properties": {
            "company": {"type": "string", "description": "the company NAME as written in the question. Never guess a ticker."}},
            "required": ["company"]}}},
    {"type": "function", "function": {
        "name": "search_trials",
        "description": "Semantic search over trial descriptions. Use for what a "
                       "trial studies or tests — mechanisms, mutations, therapies — "
                       "which no structured field holds.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "search_filings",
        "description": "Search the narrative of annual reports: what a company SAYS "
                       "about its risks, competition, regulation, or its own results.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "company": {"type": "string", "description": "optional, to narrow to one company's filing"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "patent_protection",
        "description": "How long a company's approved products stay protected, and "
                       "whether it has any. Answers patents, exclusivity, patent cliffs.",
        "parameters": {"type": "object", "properties": {
            "company": {"type": "string"}}, "required": ["company"]}}},
    {"type": "function", "function": {
        "name": "upcoming_readouts",
        "description": "Trials with a readout still ahead of them, soonest first. "
                       "Answers catalysts, expected data, when a programme reports.",
        "parameters": {"type": "object", "properties": {
            "company": {"type": "string", "description": "optional"},
            "phase": {"type": "string", "description": "optional, e.g. PHASE3"},
            "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "decline",
        "description": "The question asks for a prediction, investment advice, or "
                       "something neither the structured data nor the text can answer.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string"}}, "required": ["reason"]}}},
    {"type": "function", "function": {
        "name": "greeting",
        "description": "The message is a greeting or small talk, not a question "
                       "about the data.",
        "parameters": {"type": "object", "properties": {}}}},
]

TOOL_SYSTEM = (
    "You answer questions about a biotech company database by choosing tools. "
    "You know no company data yourself and must never state a figure that a tool "
    "did not return. Call the tools you need — more than one if the question "
    "needs composing, for example finding companies first and then checking one "
    "of them. When you have enough, stop calling tools. "
    "Every figure comes from SEC filings and ClinicalTrials.gov. Never predict, "
    "never advise buying or selling: call decline for those."
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


def _sector_labels(db):
    """
    The sector labels actually in the database, cheapest query there is.

    Hardcoded in the prompt, this list went stale the moment the universe
    widened past its original filing codes. It named three labels while the
    database held ten, so 124 medical-device companies could not be reached by
    any filter question at all — the model had no label to ask for. Reading it
    from the data means adding a sector cannot silently make companies
    invisible.
    """
    try:
        rows = db.query(Company.sector).distinct().all()
    except Exception:
        return []
    return sorted({s for (s,) in rows if s})




def _resolve_company(named, db):
    """
    Turn whatever the model put in "company" into a ticker we actually hold.

    The model is not allowed to supply the ticker itself. Asked eight times for
    Recursion's, it answered RCKT, RCRN, RECUR and RNLX and never once RXRX, and
    two of those are not tickers at all. Every one of them retrieves nothing and
    reads to the user as "we have no data on that company" while its filing sits
    in the database. Matching against the universe cannot invent a company.
    """
    if not named:
        return None
    wanted = named.strip().upper()
    if not wanted:
        return None

    rows = db.query(Company.ticker, Company.name).all()
    # a ticker, given exactly
    for ticker, _ in rows:
        if ticker and ticker.upper() == wanted:
            return ticker
    # something ticker-shaped that matched no ticker is a guess, and matching it
    # loosely against names is how RECUR would become Recursion by accident. The
    # same accident lands on the wrong company just as easily, so it stops here
    if named.strip().isupper() and len(wanted) <= 5 and wanted.isalnum():
        return None
    # the company's name, give or take the suffix every filer carries
    trimmed = re.sub(r"[^A-Z0-9 ]", " ", wanted)
    trimmed = re.sub(r"\b(INC|CORP|CORPORATION|LTD|LIMITED|PLC|SA|NV|AG|CO|"
                     r"COMPANY|HOLDINGS|GROUP|THERAPEUTICS|PHARMACEUTICALS|"
                     r"PHARMA|BIOSCIENCES|BIO|LABS|LABORATORIES)\b", " ", trimmed)
    trimmed = " ".join(trimmed.split())
    if not trimmed:
        return None
    best = None
    for ticker, name in rows:
        if not name:
            continue
        upper = name.upper()
        if upper.startswith(wanted) or wanted in upper:
            return ticker
        # fall back to the distinctive part of the name, so "Recursion" finds
        # "Recursion Pharmaceuticals, Inc."
        if trimmed and upper.startswith(trimmed):
            best = best or ticker
    return best


def _company_block(db, named):
    ticker = _resolve_company(named, db)
    facts = company_facts(db, ticker) if ticker else None
    if not facts:
        return f"No company matching {named!r} is in the database.", []
    a = facts["assessment"]
    lines = [f"{facts['ticker']}: {facts['name']} (sector: {facts['sector']})",
             f"Pipeline signal: {a['pipeline_signal']['label']}"]
    lines += [f"  - {e}" for e in a["pipeline_signal"]["evidence"]]
    lines.append(f"Financial signal: {a['financial_signal']['label']}")
    lines += [f"  - {e}" for e in a["financial_signal"]["evidence"]]
    return "\n".join(lines), [facts["ticker"]]


def _run_tool(name, args, db, as_of):
    """
    Execute one tool. Returns (facts_text, sources).

    Each returns a computed fact with the evidence behind it, never rows for the
    model to work on. A tool that finds nothing says so in words, because an
    empty string reads to the model as though it had not asked.
    """
    if name == "filter_companies":
        rows = query_companies(
            db, min_rd=args.get("min_rd"), min_cash=args.get("min_cash"),
            has_phase3=args.get("has_phase3"),
            min_active_trials=args.get("min_active_trials"),
            sector=args.get("sector"), min_runway=args.get("min_runway"),
            sort_by=args.get("sort_by"), limit=None)
        total = len(rows)
        shown = rows[:(args.get("limit") or 25)]
        if not shown:
            return "No companies match those filters.", []
        header = f"Total companies matching: {total}"
        if total > len(shown):
            header += f" (showing the first {len(shown)})"
        lines = [header, ""]
        for r in shown:
            lines.append(
                f"{r['ticker']}: {r['name']} | sector={r['sector']} | "
                f"trials={r['total_trials']} active={r['active_trials']} "
                f"phase3={'yes' if r['has_phase3'] else 'no'} | "
                f"R&D={_money(r['rd_expense'])} cash={_money(r['cash'])} "
                f"runway={r['runway'] if r['runway'] is not None else 'n/a'}")
        return "\n".join(lines), [r["ticker"] for r in shown]

    if name == "company_report":
        return _company_block(db, args.get("company"))

    if name == "search_trials":
        # an empty query would be sent to the embedding API and rejected there.
        # A tool called with nothing to search for has found nothing, which is
        # an answer rather than an error.
        query = (args.get("query") or "").strip()
        if not query:
            return "No search terms were given, so nothing was searched.", []
        trials = semantic_search(query, k=8)
        if not trials:
            return "No trial descriptions matched that.", []
        lines = ["Trials whose descriptions best match:", ""]
        for t in trials:
            snippet = (t["summary"] or "").replace("\n", " ")[:320]
            lines.append(f"{t['nct_id']} ({t['ticker']}): {t['title']} | "
                         f"{t['phase']} | {t['status']}\n  {snippet}")
        return "\n".join(lines), list(dict.fromkeys(
            t["ticker"] for t in trials if t["ticker"]))

    if name == "search_filings":
        query = (args.get("query") or "").strip()
        if not query:
            return "No search terms were given, so nothing was searched.", []
        ticker = _resolve_company(args.get("company"), db) if args.get("company") else None
        passages = search_filings(query, k=6, ticker=ticker)
        if not passages:
            return "No filing passages matched that.", []
        lines = ["Passages from annual report narrative:", ""]
        for pg in passages:
            lines.append(f"{pg['ticker']} {pg['form']} filed {pg['filed']} "
                         f"({pg['section']}):\n  {pg['text'][:600]}")
        return "\n".join(lines), list(dict.fromkeys(
            pg["ticker"] for pg in passages if pg["ticker"]))

    if name == "patent_protection":
        ticker = _resolve_company(args.get("company"), db)
        if not ticker:
            return f"No company matching {args.get('company')!r} is in the database.", []
        r = protection_for(db, ticker, as_of)
        lines = [f"{ticker} patent and exclusivity position: {r['state']}"]
        lines += [f"  - {e}" for e in r["evidence"]]
        if r.get("next_expiry"):
            lines.append(f"  - nearest expiry {r['next_expiry']}, "
                         f"furthest {r['last_expiry']}")
        return "\n".join(lines), [ticker]

    if name == "upcoming_readouts":
        ticker = _resolve_company(args.get("company"), db) if args.get("company") else None
        rows = upcoming_readouts(db, as_of, ticker=ticker, phase=args.get("phase"),
                                 limit=args.get("limit") or 25)
        if not rows:
            return "No trials with an expected readout ahead of them.", []
        lines = ["Trials with a readout still expected (estimated dates):", ""]
        for r in rows:
            lines.append(f"{r['ticker']} {r['nct_id']} | {r['phase']} | "
                         f"expected {r['completion_date']} | n={r['enrollment']} | "
                         f"{(r['conditions'] or '')[:70]}")
        return "\n".join(lines), list(dict.fromkeys(
            r["ticker"] for r in rows if r["ticker"]))

    return "", []


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


def answer_question(question, db, as_of=None):
    """
    Choose tools, run them, then phrase an answer from only what they returned.

    The two halves are kept apart deliberately. The loop decides WHAT to fetch;
    the answer step is unchanged from when a fixed plan chose it, and still sees
    nothing but the retrieved text. Choosing a tool is not inventing a number,
    and that separation is what keeps it that way.

    The loop is bounded. Composing takes more than one call — find the companies,
    then check one of them — but agentic retrieval costs a round trip and tokens
    each time, so it stops at MAX_ROUNDS whether or not the model would continue.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return {"answer": "The chat needs an OpenAI API key. Set OPENAI_API_KEY in "
                          "backend/.env (the rest of the app works without it).",
                "sources": [], "unavailable": True}

    as_of = as_of or datetime.date.today().isoformat()
    system = TOOL_SYSTEM
    labels = _sector_labels(db)
    if labels:
        system += ("\n\nThe sector labels in this database are exactly: "
                   + "; ".join(labels) + ". Use one verbatim or omit it.")

    messages = [{"role": "system", "content": system},
                {"role": "user", "content": question}]
    facts, sources, called = [], [], []

    try:
        for _ in range(MAX_ROUNDS):
            resp = _client().chat.completions.create(
                model=CHAT_MODEL, messages=messages, tools=TOOLS)
            msg = resp.choices[0].message
            if not msg.tool_calls:
                break
            messages.append({
                "role": "assistant", "content": msg.content,
                "tool_calls": [{"id": c.id, "type": "function",
                                "function": {"name": c.function.name,
                                             "arguments": c.function.arguments}}
                               for c in msg.tool_calls]})
            for call in msg.tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                called.append(name)

                # these two end the conversation rather than retrieving anything
                if name == "greeting":
                    return {"answer": GREETING, "sources": [], "tools_used": called}
                if name == "decline":
                    reason = args.get("reason") or "That is outside what this data can answer."
                    return {"answer": f"I can't answer that. {reason} I only report the "
                                      "real pipeline and financial data in the database, "
                                      "so try asking about trials by phase, R&D, cash, "
                                      "runway, patents, or expected readouts.",
                            "sources": [], "tools_used": called}

                text, srcs = _run_tool(name, args, db, as_of)
                if text:
                    facts.append(text)
                sources += srcs
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": text or "(nothing found)"})
    except Exception as e:
        return {"answer": f"Sorry, I couldn't process that question ({e}).",
                "sources": []}

    facts_text = "\n\n".join(facts)
    answer = _answer(question, facts_text)
    # "retrieved" is the exact text the answer was allowed to use. the eval
    # suite checks every claim in the answer against it (groundedness).
    return {"answer": answer, "sources": list(dict.fromkeys(sources)),
            "match_count": len(sources), "tools_used": called,
            "retrieved": facts_text}
