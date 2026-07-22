"""
This file turns the real data into simple signals you can actually explain.
Every signal is worked out from the real numbers and says why it says what it
says, so you can check it. A plain language summary can sit on top of these 
same facts later.
"""


def assess_pipeline(pipeline):
    """
    Read trial pipeline health from real trial data.
    Returns a signal dict with a label and the evidence behind it.
    """
    # pull the counts we need out of the pipeline summary
    total = pipeline["total_trials"]
    active = pipeline["active_trials"]
    terminated = pipeline["terminated_trials"]
    by_phase = pipeline["by_phase"]

    # count how advanced the pipeline is by summing any late-stage programs
    late_stage = sum(c for ph, c in by_phase.items()
                     if "PHASE3" in ph or "PHASE4" in ph)

    notes = []
    # no trials at all gets its own label and explanation
    if total == 0:
        label = "no registered trials"
        notes.append("No trials found under this sponsor name. Company may run "
                     "trials via partners, or focus on preclinical/platform work.")
    else:
        # note the overall trial counts
        notes.append(f"{total} trials: {active} active, {terminated} terminated.")
        # call out whether there are any late-stage programs
        if late_stage > 0:
            notes.append(f"{late_stage} program(s) in Phase 3+ (late-stage).")
        else:
            notes.append("Pipeline concentrated in early/mid-stage (Phase 1-2).")
        # a high termination rate is a real signal a domain expert can interpret
        if total >= 3 and terminated / total > 0.4:
            notes.append(f"High termination rate ({terminated}/{total}), worth "
                         "investigating whether strategic or efficacy-driven.")

        # pick a label based on how far along and how active the pipeline is:
        #   1. late-stage and active means the pipeline is advancing
        #   2. active but not late-stage means it is early-stage
        #   3. nothing active means the active pipeline is limited
        if late_stage > 0 and active > 0:
            label = "advancing pipeline"
        elif active > 0:
            label = "active early-stage pipeline"
        else:
            label = "limited active pipeline"

    return {"label": label, "evidence": notes}


def assess_financials(fin):
    """
    Read financial-health signals from real SEC data.
    Focus on the biotech-relevant question: cash vs. R&D burn (runway proxy).
    """
    # if there are no financials stored, say so instead of guessing
    if not fin.get("available"):
        return {"label": "financials unavailable", "evidence": [fin.get("reason", "")]}

    rd = fin.get("rd_expense")
    cash = fin.get("cash")
    notes = []
    label = "financials reported"

    # note the R&D expense and cash figures when we have them
    if rd:
        notes.append(f"R&D expense: ${rd['value']:,} (FY{rd['fiscal_year']}).")
    if cash:
        notes.append(f"Cash: ${cash['value']:,} (FY{cash['fiscal_year']}).")

    # crude runway proxy: cash divided by annual R&D burn, in years. real and checkable.
    if rd and cash and rd["value"] > 0:
        runway_years = cash["value"] / rd["value"]
        notes.append(f"Rough runway proxy: ~{runway_years:.1f}x annual R&D spend "
                     "in cash (cash / R&D expense).")
        # label the cash position by how many years of burn it covers:
        #   1. under one year is tight
        #   2. over three years is comfortable
        #   3. anything in between is moderate
        if runway_years < 1:
            label = "tight cash relative to R&D burn"
        elif runway_years > 3:
            label = "comfortable cash relative to R&D burn"
        else:
            label = "moderate cash relative to R&D burn"

    return {"label": label, "evidence": notes}


def build_assessment(company_name, pipeline, financials):
    """Combine the signals into one grounded assessment object."""
    return {
        "company": company_name,
        "pipeline_signal": assess_pipeline(pipeline),
        "financial_signal": assess_financials(financials),
        "disclaimer": ("Grounded in primary-source trial (ClinicalTrials.gov) "
                       "and filing (SEC EDGAR) data. Informational only, not "
                       "investment advice."),
    }

