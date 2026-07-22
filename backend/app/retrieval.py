"""
This is the shared retrieval layer over the database, used by both the companies
endpoint and the chat. For structured questions like phase, financials, or
filtering, the right way to look things up is a real database query and not a
vector search, so the results come back exact and complete.
"""

from .models import Company
from .data_sources import summarize_pipeline
from .analysis import build_assessment


def trials_from_db(company):
    # flatten each stored trial row into a plain dict
    return [{
        "nct_id": t.nct_id, "title": t.title, "phase": t.phase,
        "status": t.status, "lead_sponsor": t.lead_sponsor,
    } for t in company.trials]


def financials_from_db(company):
    # rebuild the {available, rd_expense, cash} dict that analysis.assess_financials wants
    fins = {f.metric: {"value": int(f.value), "fiscal_year": f.fiscal_year}
            for f in company.financials}
    # no financials stored means we honestly say they're unavailable
    if not fins:
        return {"available": False, "reason": "no financials stored for this company"}
    return {"available": True, "rd_expense": fins.get("rd_expense"),
            "cash": fins.get("cash")}


def late_stage_count(by_phase):
    # count the trials in Phase 3 or Phase 4, which are the late-stage programs
    return sum(c for ph, c in by_phase.items() if "PHASE3" in ph or "PHASE4" in ph)


def query_companies(db, min_rd=None, min_cash=None, has_phase3=None,
                    min_active_trials=None, sector=None, min_runway=None,
                    sort_by=None, limit=None):
    """
    The one filter both /companies and the chat use. Reads every company, applies
    the (all optional, AND-ed) filters, returns compact summary dicts.
    sort_by ("rd"/"cash"/"active_trials"/"total_trials"/"runway") sorts descending
    (for "most"/"highest" questions); limit caps the count.
    """
    results = []
    # walk every company and build up its summary as we go
    for c in db.query(Company).all():
        # pull this company's trials and roll them up into a pipeline summary
        trials = trials_from_db(c)
        pipeline = summarize_pipeline(trials)
        # pull its financials and grab the R&D and cash figures
        fins = {f.metric: {"value": int(f.value), "fiscal_year": f.fiscal_year}
                for f in c.financials}
        rd, cash = fins.get("rd_expense"), fins.get("cash")
        late = late_stage_count(pipeline["by_phase"])
        # crude runway proxy (cash divided by annual R&D burn), when both are known.
        # keep an exact value for filtering and a rounded one for display, so a
        # min_runway filter doesn't wrongly include a company at say 0.998 that
        # only rounds up to 1.0.
        runway = runway_exact = None
        if rd and cash and rd["value"] > 0:
            runway_exact = cash["value"] / rd["value"]
            runway = round(runway_exact, 2)

        # apply each optional filter, skipping this company if it fails one:
        # skip if its R&D expense is below the minimum
        if min_rd is not None and (not rd or rd["value"] < min_rd):
            continue
        # skip if its cash is below the minimum
        if min_cash is not None and (not cash or cash["value"] < min_cash):
            continue
        # has_phase3 works both ways: True keeps only late-stage companies,
        # False keeps only those without a Phase 3+ program.
        if has_phase3 is True and late == 0:
            continue
        if has_phase3 is False and late > 0:
            continue
        # skip if it has fewer active trials than asked for
        if min_active_trials is not None and pipeline["active_trials"] < min_active_trials:
            continue
        # skip if its sector doesn't match the requested one
        if sector and (c.sector or "").lower() != sector.lower():
            continue
        # skip if its exact runway is below the minimum
        if min_runway is not None and (runway_exact is None or runway_exact < min_runway):
            continue

        # this company passed every filter, so add its summary to the results
        results.append({
            "ticker": c.ticker,
            "name": c.name,
            "sector": c.sector,
            "total_trials": pipeline["total_trials"],
            "active_trials": pipeline["active_trials"],
            "has_phase3": late > 0,
            "rd_expense": rd,
            "cash": cash,
            "runway": runway,
        })

    # sort by a requested metric (descending) if asked, otherwise by ticker
    keymap = {
        "rd": lambda r: (r["rd_expense"] or {}).get("value", -1),
        "cash": lambda r: (r["cash"] or {}).get("value", -1),
        "active_trials": lambda r: r["active_trials"],
        "total_trials": lambda r: r["total_trials"],
        "runway": lambda r: r["runway"] if r["runway"] is not None else -1,
    }
    # sort descending by the requested metric, otherwise fall back to ticker order
    if sort_by in keymap:
        results.sort(key=keymap[sort_by], reverse=True)
    else:
        results.sort(key=lambda r: r["ticker"])
    # cap the number of results if a limit was given
    if limit:
        results = results[:limit]
    return results


def company_facts(db, ticker):
    """Full grounded facts for one company (or None if it isn't in the DB)."""
    # look the company up by ticker, returning None if it isn't stored
    c = db.get(Company, ticker.upper())
    if c is None:
        return None
    # gather its trials, pipeline summary, financials, and the derived assessment
    trials = trials_from_db(c)
    pipeline = summarize_pipeline(trials)
    financials = financials_from_db(c)
    assessment = build_assessment(c.name, pipeline, financials)
    return {
        "ticker": c.ticker, "name": c.name, "sector": c.sector,
        "pipeline": pipeline, "financials": financials, "assessment": assessment,
    }
