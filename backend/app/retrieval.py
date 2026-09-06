"""
This is the shared retrieval layer over the database, used by both the companies
endpoint and the chat. For structured questions about phase, financials or
filtering, the right way to look things up is a real database query and not a
vector search, so the results come back exact and complete rather than merely
close. Imported by main.py and by chat.py, whose typed accessors are thin
wrappers over these functions.
"""

from .models import Company, FINANCIAL_METRICS
from .data_sources import summarize_pipeline
from .analysis import build_assessment, annual_burn, available_liquidity


def trials_from_db(company):
    # flatten each stored trial row into a plain dict
    return [{
        "nct_id": t.nct_id, "title": t.title, "phase": t.phase,
        "status": t.status, "lead_sponsor": t.lead_sponsor,
        # lead or collaborator. Carried through so a reader can ask whether this
        # is the company's own trial or one it partners on, rather than having
        # the two silently added together
        "role": t.role,
        # what it treats and when it reports, which is what turns "Phase 3,
        # recruiting" into "Phase 3, atopic dermatitis, reading out Q2 2026"
        "conditions": t.conditions,
        "completion_date": t.completion_date,
        "completion_date_type": t.completion_date_type,
        "enrollment": t.enrollment,
        "has_results": t.has_results,
    } for t in company.trials]


def metrics_from_db(company):
    """
    {metric: figure} for one company, keyed by "rd_expense" and "cash". Each figure
    carries the period it covers, because the two are not the same kind of number:
    R&D is a total over a full year, cash is a balance on a date.
    """
    # The table holds a row per fiscal year, so "the figure" has to be chosen
    # rather than taken. Sorting by period end and letting the last write win
    # makes it the newest; without that the dict comprehension kept whatever
    # row the iteration happened to end on, which is a different year for
    # different companies and no error anywhere to say so.
    return {f.metric: {"value": int(f.value), "fiscal_year": f.fiscal_year,
                       "fiscal_period": f.fiscal_period, "period_end": f.period_end}
            for f in sorted(company.financials, key=_period_key)}


def _period_key(f):
    """Order financial rows oldest first, so the last one read is the newest."""
    return (f.period_end or "", f.fiscal_year or 0)


def history_from_db(company):
    """
    {metric: [figure, ...]} newest first, the series behind the single figure.

    Kept separate from metrics_from_db rather than replacing it: everything that
    reads a company's cash wants one number, and only the questions about a
    trend want the list.
    """
    out = {}
    # annual rows only. The table also holds the current figure, which for a
    # balance is usually a quarter end, and a series that mixed one quarter in
    # among nine year ends would read as a year that fell off a cliff.
    for f in sorted(company.financials, key=_period_key, reverse=True):
        if f.fiscal_period != "FY":
            continue
        out.setdefault(f.metric, []).append(
            {"value": int(f.value), "fiscal_year": f.fiscal_year,
             "fiscal_period": f.fiscal_period, "period_end": f.period_end})
    return out


def financials_from_db(company):
    # rebuild the {available, rd_expense, cash} dict that analysis.assess_financials wants
    fins = metrics_from_db(company)
    # no financials stored means we honestly say they're unavailable
    if not fins:
        return {"available": False, "reason": "no financials stored for this company"}
    # every metric is present whether or not it was reported, so callers can read
    # a figure without checking the key exists first. driven off the model's list
    # rather than a fixed pair, so adding a figure to ingestion surfaces it here.
    return {"available": True,
            **{metric: fins.get(metric) for metric in FINANCIAL_METRICS}}


def derived_figures(fin):
    """
    The numbers computed from the stored ones: what a company has to spend, how
    fast it spends it, and how long that lasts. Returned as data so anything
    displaying them shows this calculation rather than repeating it.
    """
    if not fin.get("available"):
        return {"liquidity": None, "burn": None, "burn_source": None,
                "runway": None, "cash_generative": False}

    liquidity, liquidity_note = available_liquidity(fin)
    burn, burn_source = annual_burn(fin)
    ocf = fin.get("operating_cash_flow")
    return {
        "liquidity": liquidity,
        # says whether marketable securities were folded in, since that is the
        # difference between a runway of one year and one of seven
        "liquidity_note": liquidity_note,
        "burn": burn,
        "burn_source": burn_source,
        "runway": round(liquidity["value"] / burn, 2)
        if burn and liquidity else None,
        # a company funding itself has no runway to report, which is different
        # from one whose runway we simply couldn't work out
        "cash_generative": bool(burn is None and ocf and ocf["value"] >= 0),
    }


def late_stage_count(by_phase):
    # count the trials in Phase 3 or Phase 4, which are the late-stage programs
    return sum(c for ph, c in by_phase.items() if "PHASE3" in ph or "PHASE4" in ph)


def _pipelines_by_ticker(db):
    """
    {ticker: pipeline summary}, from one grouped query.

    Selects the three columns the rollup needs and nothing else. The point is
    what it leaves behind: Trial carries an embedding, and loading rows as ORM
    objects brings it along.
    """
    from sqlalchemy import func
    from .models import Trial

    rows = (db.query(Trial.company_ticker, Trial.phase, Trial.status, Trial.role,
                     func.count().label("n"))
              .group_by(Trial.company_ticker, Trial.phase, Trial.status, Trial.role)
              .all())
    ACTIVE = ("RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION")
    out = {}
    for ticker, phase, status, role, n in rows:
        p = out.setdefault(ticker, {"total_trials": 0, "by_phase": {},
                                    "by_status": {}, "active_trials": 0,
                                    "terminated_trials": 0,
                                    "collaborator_trials": 0})
        # a trial the company does not lead is counted apart and never added in,
        # exactly as summarize_pipeline does it
        if (role or "lead") != "lead":
            p["collaborator_trials"] += n
            continue
        p["total_trials"] += n
        p["by_phase"][phase] = p["by_phase"].get(phase, 0) + n
        p["by_status"][status] = p["by_status"].get(status, 0) + n
        if status in ACTIVE:
            p["active_trials"] += n
        if status == "TERMINATED":
            p["terminated_trials"] += n
    return out


def _financials_by_ticker(db):
    """{ticker: {metric: figure}}, from one query rather than one per company."""
    from .models import Financial

    out = {}
    # ordered oldest first so the last row written for a metric is the newest,
    # the same rule metrics_from_db follows
    for f in sorted(db.query(Financial).all(), key=_period_key):
        out.setdefault(f.company_ticker, {})[f.metric] = {
            "value": int(f.value), "fiscal_year": f.fiscal_year,
            "fiscal_period": f.fiscal_period, "period_end": f.period_end}
    return out


def query_companies(db, min_rd=None, min_cash=None, has_phase3=None,
                    min_active_trials=None, sector=None, min_runway=None,
                    sort_by=None, limit=None):
    """
    The one filter both /companies and the chat use. Reads every company, applies
    the (all optional, AND-ed) filters, returns compact summary dicts.
    sort_by ("rd"/"cash"/"active_trials"/"total_trials"/"runway") sorts descending
    (for "most"/"highest" questions); limit caps the count.
    """
    # Two aggregate queries rather than two per company.
    #
    # This walked every company and lazy-loaded its trials and financials, which
    # is 787 companies against roughly 1,600 queries, and the trial load pulled
    # whole ORM objects, embedding column included. Counting phases was dragging
    # 30,142 vectors of 1,536 floats out of the database, about 185 MB, to
    # render a table that shows none of it. The browse endpoint took 7.6
    # seconds, and the page calls it twice on load, so the universe banner sat
    # on "Loading…" for fifteen.
    pipelines = _pipelines_by_ticker(db)
    financials = _financials_by_ticker(db)

    results = []
    for c in db.query(Company).all():
        pipeline = pipelines.get(c.ticker) or summarize_pipeline([])
        fins = financials.get(c.ticker, {})
        rd, cash = fins.get("rd_expense"), fins.get("cash")
        late = late_stage_count(pipeline["by_phase"])
        # runway: cash divided by a year of burn, when both are known. burn comes
        # from operating cash flow where it was reported and falls back to R&D
        # expense otherwise, which is why the source travels with it.
        # keep an exact value for filtering and a rounded one for display, so a
        # min_runway filter doesn't wrongly include a company at say 0.998 that
        # only rounds up to 1.0.
        burn, burn_source = annual_burn(fins)
        # cash alone understates what a company has to spend, so runway divides
        # liquidity (cash plus marketable securities, when their dates agree)
        liquidity, _ = available_liquidity(fins)
        runway = runway_exact = None
        if burn and liquidity:
            runway_exact = liquidity["value"] / burn
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
            # what the sponsor really has, when we only fetched part of it, so a
            # partial pipeline can be labelled partial instead of passing for whole
            "total_trials_reported": c.trial_count_total,
            "trials_truncated": bool(c.trials_truncated),
            "active_trials": pipeline["active_trials"],
            "has_phase3": late > 0,
            "rd_expense": rd,
            "cash": cash,
            "revenue": fins.get("revenue"),
            "runway": runway,
            # which figure the runway was divided by, since R&D expense is the
            # weaker fallback and a reader should be able to tell them apart
            "burn_source": burn_source,
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
    # say so when the stored trials are only part of what the sponsor registered
    pipeline["total_trials_reported"] = c.trial_count_total
    pipeline["truncated"] = bool(c.trials_truncated)
    financials = financials_from_db(c)
    assessment = build_assessment(c.name, pipeline, financials)
    return {
        "ticker": c.ticker, "name": c.name, "sector": c.sector,
        "pipeline": pipeline, "financials": financials,
        # the figures worked out from the raw ones, computed here rather than
        # left for whatever is displaying them. runway in particular has real
        # rules behind it (which balance counts, which burn figure, whether it
        # applies at all), and a second implementation in the UI would quietly
        # disagree with this one the moment either changed.
        "derived": derived_figures(financials),
        "assessment": assessment,
    }


def upcoming_readouts(db, as_of, ticker=None, phase=None, limit=25):
    """
    Trials with a readout still ahead of them, soonest first.

    A completion date is only a catalyst if it has not happened yet and was
    never claimed to have happened: the registry marks a date ACTUAL or
    ESTIMATED, and only an ESTIMATED one in the future is a forecast readout.
    Reading an ACTUAL date the same way would turn history into a prediction.

    Lead trials only. A readout the company does not run is not its catalyst to
    report, and the pipeline counts exclude those for the same reason.
    """
    from .models import Trial

    q = (db.query(Trial)
           .filter(Trial.completion_date_type == "ESTIMATED",
                   Trial.completion_date >= as_of,
                   Trial.role == "lead"))
    if ticker:
        q = q.filter(Trial.company_ticker == ticker)
    if phase:
        q = q.filter(Trial.phase.like(f"%{phase}%"))
    rows = q.order_by(Trial.completion_date).limit(limit).all()
    return [{"nct_id": t.nct_id, "ticker": t.company_ticker, "title": t.title,
             "phase": t.phase, "status": t.status,
             "completion_date": t.completion_date,
             "conditions": t.conditions, "enrollment": t.enrollment}
            for t in rows]
