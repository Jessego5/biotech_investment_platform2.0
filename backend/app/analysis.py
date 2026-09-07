"""
This turns the real data into simple signals that can be explained. Every signal
is worked out from the real numbers and says why it says what it says, so any of
them can be checked, and a plain language summary can sit on top of the same
facts later. Imported by main.py, which calls build_assessment for a company's
page.

Every figure it writes down goes through units.money, because a number here is
only true with the currency it was reported in attached.
"""

from .units import money, same_unit


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


def _as_of(entry):
    """
    How to describe when a balance was measured. Prefer the actual date the figure
    was reported for, and fall back to the fiscal year for a figure stored before
    the date was recorded, so an older row still reads honestly rather than blank.
    """
    if entry.get("period_end"):
        return f"as of {entry['period_end']}"
    if entry.get("fiscal_year"):
        return f"FY{entry['fiscal_year']}"
    return "period not recorded"


# beyond this many years, runway stops being a useful description of a company
# and becomes an artefact of dividing by a burn near zero. the number is still
# computed and returned, since it is the honest arithmetic, but it is labelled
# rather than presented as a meaningful estimate.
RUNWAY_NOT_MEANINGFUL = 10


def burn_figure(fin):
    """
    The figure annual_burn divided by, so a caller can check its unit against
    the cash it is about to be divided into. A ratio of kroner to dollars is
    not a number of years.
    """
    return fin.get("operating_cash_flow") or fin.get("rd_expense")


def available_liquidity(fin):
    """
    What a company actually has to spend. Returns (liquidity, note), the note
    explaining the combination for the evidence list.

    Cash alone is not it: CRISPR Therapeutics holds $291m of cash against $2.06b
    of marketable securities, so runway from cash said under a year when the real
    answer was nearly seven. The two are only added when reported as of the same
    date, since a company that stopped holding securities keeps its last figure
    forever, and adding Recursion's from 2022 to cash from 2026 would invent $405m.
    """
    cash = fin.get("cash")
    securities = fin.get("marketable_securities")
    if not cash:
        return None, None

    if not securities:
        return cash, None

    # and only the same currency. A company reporting cash in one unit and
    # securities in another is not a company with a bigger balance, it is two
    # numbers that cannot be added
    if not same_unit(cash, securities):
        return cash, (
            f"Marketable securities of {money(securities['value'], securities.get('unit'))} "
            f"are reported in a different unit from the cash figure, so they "
            f"are left out rather than added to it.")

    # only the same balance date can be added together
    if securities.get("period_end") != cash.get("period_end"):
        return cash, (
            f"Marketable securities of {money(securities['value'], securities.get('unit'))} were last "
            f"reported as of {securities['period_end']}, which is a different "
            f"date from the cash figure, so they are left out rather than added "
            f"to a balance from another period.")

    total = cash["value"] + securities["value"]
    return ({**cash, "value": total},
            f"Liquidity: {money(total, cash.get('unit'))} (cash plus marketable "
            f"securities of {money(securities['value'], securities.get('unit'))}, "
            f"both as of {cash['period_end']}).")


def annual_burn(fin):
    """
    How much cash a year of running the business consumes, and where that came
    from. Returns (burn, source), with burn None when there is nothing to divide
    by: no figures, or a company whose operations generate cash.

    Operating cash flow is the real answer, reported negative while a company
    spends more than it takes in. R&D expense is the fallback and is not a cash
    figure at all, missing in both directions: Recursion reports $475m of R&D
    against $372m actually spent. So the source travels with the number.
    """
    ocf = fin.get("operating_cash_flow")
    if ocf:
        # positive means operations produced cash, so there is no burn to measure
        return (-ocf["value"], "operating cash flow") if ocf["value"] < 0 \
            else (None, "operating cash flow")

    rd = fin.get("rd_expense")
    if rd and rd["value"] > 0:
        return rd["value"], "R&D expense"
    return None, None


def assess_financials(fin):
    """
    Read financial-health signals from real SEC data.
    Focus on the biotech-relevant question: cash against the rate it is spent.
    """
    # if there are no financials stored, say so instead of guessing
    if not fin.get("available"):
        return {"label": "financials unavailable", "evidence": [fin.get("reason", "")]}

    rd = fin.get("rd_expense")
    cash = fin.get("cash")
    revenue = fin.get("revenue")
    ocf = fin.get("operating_cash_flow")
    notes = []
    label = "financials reported"

    # note each figure we have, labelled with the period it actually covers. these
    # are different kinds of number: spending is a full year's total, cash is the
    # balance on a date, usually a more recent one from a quarterly filing.
    # calling them all a fiscal year would hide that.
    if rd:
        notes.append(f"R&D expense: {money(rd['value'], rd.get('unit'))} (FY{rd['fiscal_year']}, "
                     "full year).")
    if ocf:
        # sign it the way a reader expects: cash consumed, or cash generated
        direction = "used in" if ocf["value"] < 0 else "from"
        notes.append(f"Cash {direction} operations: {money(abs(ocf['value']), ocf.get('unit'))} "
                     f"(FY{ocf['fiscal_year']}, full year).")
    if cash:
        notes.append(f"Cash: {money(cash['value'], cash.get('unit'))} ({_as_of(cash)}).")

    # cash alone is not what a company has to spend, so show the combination and
    # how it was reached
    liquidity, liquidity_note = available_liquidity(fin)
    if liquidity_note:
        notes.append(liquidity_note)

    # debt is not netted off the runway, because runway answers "how long can
    # this be funded", not "what is left for shareholders". saying it separately
    # keeps both questions answerable.
    debt = fin.get("debt")
    if debt and debt["value"] > 0:
        note = (f"Debt: {money(debt['value'], debt.get('unit'))} ({_as_of(debt)}), which the "
                "runway below does not account for.")
        # a company that repaid its borrowing stops reporting the tag, leaving
        # the last figure in the record indefinitely. so a debt date older than
        # the cash date says nothing about what is outstanding now, the same trap
        # the securities figures set.
        if cash and debt.get("period_end") and cash.get("period_end") \
                and debt["period_end"] < cash["period_end"]:
            note += (f" That is older than the cash figure of "
                     f"{cash['period_end']}, so it may since have been repaid "
                     "or refinanced.")
        notes.append(note)

    # revenue splits the universe into two kinds of company that aren't really
    # comparable: one selling a product, one spending toward a readout
    if revenue and revenue["value"] > 0:
        notes.append(f"Revenue: {money(revenue['value'], revenue.get('unit'))} (FY{revenue['fiscal_year']}, "
                     "full year), so this is a commercial-stage company.")
    elif revenue is not None:
        notes.append("No product revenue reported, so this is a pre-revenue "
                     "company funded by its cash balance.")

    burn, source = annual_burn(fin)

    # a company whose operations generate cash isn't running down a balance, so
    # runway is the wrong question to ask about it
    if burn is None and ocf and ocf["value"] >= 0:
        label = "cash generative"
        notes.append("Operations generated cash over the last full year, so a "
                     "runway estimate does not apply.")
    # runway: what the company has to spend divided by a year of burn. real and
    # checkable, and built on liquidity rather than cash alone.
    elif burn and liquidity:
        runway_years = liquidity["value"] / burn
        # a note is also written when securities were EXCLUDED for being stale,
        # so the wording has to key off whether they were actually added
        held = "liquidity" if liquidity["value"] != cash["value"] else "cash"
        notes.append(f"Rough runway proxy: ~{runway_years:.1f} years at the last "
                     f"full year's burn (most recent {held} / {source}).")
        if source == "R&D expense":
            notes.append("Burn is approximated from R&D expense because no "
                         "operating cash flow was reported. R&D is not cash "
                         "spent: it excludes G&A and includes non-cash charges, "
                         "so this figure may be off in either direction.")
        # label the cash position by how many years of burn it covers:
        #   1. under one year is tight
        #   2. over three years is comfortable
        #   3. anything in between is moderate
        if runway_years < 1:
            label = "tight cash relative to burn"
        # past a certain point the figure stops describing anything. a company
        # near breakeven burns so little that dividing its balance by that burn
        # produces a huge number with false precision: Zevra has $221m against
        # $1.6m of annual burn, which is arithmetically 138 years and practically
        # just means cash is not what constrains it.
        elif runway_years > RUNWAY_NOT_MEANINGFUL:
            label = "minimal burn relative to liquidity"
            notes.append(f"Burn is small enough relative to liquidity that a "
                         f"runway figure says little: over "
                         f"{RUNWAY_NOT_MEANINGFUL:.0f} years at the last full "
                         "year's rate.")
        elif runway_years > 3:
            label = "comfortable cash relative to burn"
        else:
            label = "moderate cash relative to burn"

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

