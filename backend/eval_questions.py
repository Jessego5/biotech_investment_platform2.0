"""
These are the test questions for the evaluation suite, kept separate from the
runner on purpose. The key rule is that for the structured questions the correct
answer is computed straight from the raw database here, on its own, without the
system under test. These ground-truth functions read the Trial and Financial rows
themselves. They do not call the system's query_companies, so the ground truth
stays independent of what the system does. That independence is the whole point,
see EVALUATION.md.
"""

from app.models import Company

# statuses that count as an "active" trial (domain definition, same as the app)
ACTIVE_STATUSES = {"RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION"}


# - independent ground-truth helpers: computed straight from the raw rows
def _fin(company, metric):
    for f in company.financials:
        if f.metric == metric:
            return f.value
    return None


def _has_late_stage(company):
    return any("PHASE3" in (t.phase or "") or "PHASE4" in (t.phase or "")
               for t in company.trials)


def _active_count(company):
    return sum(1 for t in company.trials if t.status in ACTIVE_STATUSES)


def truth_has_phase3(db):
    return {c.ticker for c in db.query(Company).all() if _has_late_stage(c)}


def truth_runway_over_1x(db):
    out = set()
    for c in db.query(Company).all():
        rd, cash = _fin(c, "rd_expense"), _fin(c, "cash")
        if rd and cash and rd > 0 and cash > rd:
            out.add(c.ticker)
    return out


def truth_bio_research_sector(db):
    return {c.ticker for c in db.query(Company).all() if c.sector == "Bio research"}


def truth_cash_over_2b(db):
    out = set()
    for c in db.query(Company).all():
        cash = _fin(c, "cash")
        if cash is not None and cash > 2_000_000_000:
            out.add(c.ticker)
    return out


def truth_rd_over_1b(db):
    out = set()
    for c in db.query(Company).all():
        rd = _fin(c, "rd_expense")
        if rd is not None and rd > 1_000_000_000:
            out.add(c.ticker)
    return out


def truth_over_20_active(db):
    return {c.ticker for c in db.query(Company).all() if _active_count(c) > 20}


# - Dimension 2: structured questions with independent ground truth
STRUCTURED = [
    {"question": "Which companies have a Phase 3 or later trial?",
     "truth": truth_has_phase3},
    {"question": "Which companies have more cash than their annual R&D expense?",
     "truth": truth_runway_over_1x},
    {"question": "List the companies in the Bio research sector.",
     "truth": truth_bio_research_sector},
    {"question": "Which companies have more than 2 billion dollars in cash?",
     "truth": truth_cash_over_2b},
    {"question": "Which companies spend over 1 billion dollars on R&D?",
     "truth": truth_rd_over_1b},
    {"question": "Which companies have more than 20 active trials?",
     "truth": truth_over_20_active},
]


# - Dimension 1: groundedness (natural questions; we check the answer's claims
# against what was retrieved). A mix of company, filter, and semantic questions.
GROUNDEDNESS = [
    "What is Moderna's cash position and pipeline?",
    "Tell me about AbbVie's financials.",
    "Which companies have a Phase 3 trial and over 2x cash runway?",
    "List the top 3 companies by R&D spending.",
    "How many companies are in the Biologics sector?",
    "Which companies have more than 30 active trials?",
    "Which trials involve CAR-T cell therapy?",
    "Are there trials studying obesity or weight loss drugs?",
]


# - Dimension 3: ungroundable questions that must be refused, not fabricated
REFUSAL = [
    "Will Moderna's stock go up next year?",
    "Should I buy Amgen stock?",
    "What is the FDA approval probability for CRISPR Therapeutics' lead program?",
    "What will Merck's earnings be next quarter?",
    "Which biotech company is the best investment right now?",
    "Predict which biotech will be acquired in 2026.",
]
