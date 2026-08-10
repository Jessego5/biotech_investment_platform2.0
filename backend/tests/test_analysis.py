"""
These are the tests for the grounded signal layer. They pin the thresholds that
analysis.py turns real numbers into labels with, exactly and on the boundary: a
runway of exactly 1.0x is moderate and not tight, a 0.4 termination rate does not
trip the high-termination flag, and zero R&D never divides by zero. These rules
are what the whole app's credibility rests on, so a label should only ever change
because someone deliberately changed the rule. Run them with pytest.
"""

from app.analysis import (assess_pipeline, assess_financials, build_assessment,
                          annual_burn, available_liquidity)


def pipeline(total=0, active=0, terminated=0, by_phase=None):
    """Build the pipeline summary dict that assess_pipeline expects."""
    return {"total_trials": total, "active_trials": active,
            "terminated_trials": terminated, "by_phase": by_phase or {}}


# - assess_pipeline

def test_no_trials_says_so_instead_of_guessing():
    signal = assess_pipeline(pipeline(total=0))
    assert signal["label"] == "no registered trials"
    # it should explain why rather than implying the company does nothing
    assert "preclinical/platform" in " ".join(signal["evidence"])


def test_late_stage_and_active_is_advancing():
    signal = assess_pipeline(pipeline(total=2, active=1,
                                      by_phase={"PHASE3": 1, "PHASE1": 1}))
    assert signal["label"] == "advancing pipeline"
    assert "1 program(s) in Phase 3+" in " ".join(signal["evidence"])


def test_active_without_late_stage_is_early_stage():
    signal = assess_pipeline(pipeline(total=2, active=2,
                                      by_phase={"PHASE1": 1, "PHASE2": 1}))
    assert signal["label"] == "active early-stage pipeline"
    assert "early/mid-stage" in " ".join(signal["evidence"])


def test_late_stage_but_nothing_active_is_limited():
    # a Phase 3 that is completed or terminated is not an advancing pipeline
    signal = assess_pipeline(pipeline(total=1, active=0, by_phase={"PHASE3": 1}))
    assert signal["label"] == "limited active pipeline"


def test_combined_phase_string_counts_as_late_stage():
    # ClinicalTrials.gov reports phase as a joined string for straddling trials,
    # so "PHASE2, PHASE3" has to count toward late-stage
    signal = assess_pipeline(pipeline(total=1, active=1,
                                      by_phase={"PHASE2, PHASE3": 1}))
    assert signal["label"] == "advancing pipeline"


def test_phase4_counts_as_late_stage():
    signal = assess_pipeline(pipeline(total=1, active=1, by_phase={"PHASE4": 1}))
    assert signal["label"] == "advancing pipeline"


def test_high_termination_rate_is_flagged():
    # 3 of 5 terminated is 0.6, over the 0.4 threshold
    signal = assess_pipeline(pipeline(total=5, active=1, terminated=3,
                                      by_phase={"PHASE1": 5}))
    assert "High termination rate (3/5)" in " ".join(signal["evidence"])


def test_termination_flag_needs_at_least_three_trials():
    # 1 of 2 is a 0.5 rate but the sample is too small to mean anything
    signal = assess_pipeline(pipeline(total=2, active=1, terminated=1,
                                      by_phase={"PHASE1": 2}))
    assert "High termination rate" not in " ".join(signal["evidence"])


def test_termination_threshold_is_strictly_above_forty_percent():
    # exactly 0.4 (2 of 5) must not trip the flag
    signal = assess_pipeline(pipeline(total=5, active=1, terminated=2,
                                      by_phase={"PHASE1": 5}))
    assert "High termination rate" not in " ".join(signal["evidence"])


# - assess_financials

def financials(rd=None, cash=None, fiscal_year=2024, cash_as_of=None,
               operating_cash_flow=None, revenue=None, securities=None,
               securities_as_of=None, debt=None, debt_as_of=None):
    """
    Build the financials dict that assess_financials expects. The period totals
    (R&D, cash flow, revenue) cover a full year; cash is a balance on a date,
    usually a more recent one. operating_cash_flow is negative while a company is
    spending more than it takes in, which is how SEC reports it.
    """
    out = {"available": True}
    for metric, value in (("rd_expense", rd),
                          ("operating_cash_flow", operating_cash_flow),
                          ("revenue", revenue)):
        if value is not None:
            out[metric] = {"value": value, "fiscal_year": fiscal_year,
                           "fiscal_period": "FY",
                           "period_end": f"{fiscal_year}-12-31"}
    for metric, value, as_of in (("cash", cash, cash_as_of),
                                 ("marketable_securities", securities,
                                  securities_as_of),
                                 ("debt", debt, debt_as_of)):
        if value is not None:
            out[metric] = {"value": value, "fiscal_year": fiscal_year,
                           "fiscal_period": "Q2",
                           "period_end": as_of or f"{fiscal_year}-12-31"}
    return out


def test_unavailable_financials_report_the_reason():
    signal = assess_financials({"available": False, "reason": "IFRS filer"})
    assert signal["label"] == "financials unavailable"
    assert signal["evidence"] == ["IFRS filer"]


def test_runway_under_one_year_is_tight():
    signal = assess_financials(financials(rd=100, cash=50))
    assert signal["label"] == "tight cash relative to burn"


def test_runway_over_three_years_is_comfortable():
    signal = assess_financials(financials(rd=100, cash=400))
    assert signal["label"] == "comfortable cash relative to burn"


def test_runway_of_exactly_one_year_is_moderate():
    # the boundary is "< 1 is tight", so exactly 1.0 must not be tight
    signal = assess_financials(financials(rd=100, cash=100))
    assert signal["label"] == "moderate cash relative to burn"


def test_a_near_breakeven_company_is_not_given_a_precise_runway():
    # Zevra: $221m of liquidity against $1.6m of annual burn is arithmetically
    # 138 years, which says nothing except that cash is not its constraint. a
    # figure that large is false precision, not information.
    signal = assess_financials(financials(cash=145_321_000,
                                          securities=76_249_000,
                                          operating_cash_flow=-1_598_000))

    assert signal["label"] == "minimal burn relative to liquidity"
    assert "says little" in " ".join(signal["evidence"])


def test_the_meaningfulness_ceiling_is_a_boundary_not_a_range():
    # just under stays a normal comfortable reading
    signal = assess_financials(financials(cash=999, operating_cash_flow=-100))
    assert signal["label"] == "comfortable cash relative to burn"

    # just over crosses into the not-meaningful bucket
    signal = assess_financials(financials(cash=1001, operating_cash_flow=-100))
    assert signal["label"] == "minimal burn relative to liquidity"


def test_runway_of_exactly_three_years_is_moderate():
    # the boundary is "> 3 is comfortable", so exactly 3.0 must not be comfortable
    signal = assess_financials(financials(rd=100, cash=300))
    assert signal["label"] == "moderate cash relative to burn"


def test_zero_rd_does_not_divide_by_zero():
    signal = assess_financials(financials(rd=0, cash=500))
    # no runway can be computed, so it must not claim one
    assert signal["label"] == "financials reported"
    assert "runway" not in " ".join(signal["evidence"]).lower()


def test_cash_without_rd_reports_cash_but_no_runway():
    signal = assess_financials(financials(cash=500))
    assert signal["label"] == "financials reported"
    assert "Cash: $500" in " ".join(signal["evidence"])
    assert "runway" not in " ".join(signal["evidence"]).lower()


def test_evidence_shows_the_real_figures_and_their_periods():
    signal = assess_financials(financials(rd=1_500_000, cash=9_000_000,
                                          fiscal_year=2023,
                                          cash_as_of="2024-06-30"))
    evidence = " ".join(signal["evidence"])
    # the numbers a reader would check the claim against, each labelled with the
    # period it covers: a year of spending, and a balance on a date
    assert "R&D expense: $1,500,000 (FY2023, full year)." in evidence
    assert "Cash: $9,000,000 (as of 2024-06-30)." in evidence
    assert "~6.0 years at the last full year's burn" in evidence


def test_cash_is_not_labelled_as_a_fiscal_year():
    # cash usually comes from a quarterly filing, so calling it FY2025 would say
    # the company had that much at its year end, which is a different claim
    signal = assess_financials(financials(rd=100, cash=500, fiscal_year=2025,
                                          cash_as_of="2026-06-30"))

    assert "Cash: $500 (as of 2026-06-30)." in " ".join(signal["evidence"])


def test_cash_with_no_recorded_date_falls_back_to_the_fiscal_year():
    # a row stored before the date was recorded should still read honestly
    signal = assess_financials(
        {"available": True, "cash": {"value": 500, "fiscal_year": 2024}})

    assert "Cash: $500 (FY2024)." in " ".join(signal["evidence"])


def test_the_runway_note_says_which_two_numbers_it_divided():
    # the figures come from different periods, so the note has to be specific or
    # the reader can't check it
    signal = assess_financials(financials(rd=100, cash=300))

    assert "most recent cash / R&D expense" in " ".join(signal["evidence"])


# - liquidity: the numerator of runway

def test_liquidity_adds_securities_reported_on_the_same_date():
    # CRISPR Therapeutics holds $291m of cash and $2.06b of securities, both as
    # of the same date. cash alone said under a year of runway; the real answer
    # was nearly seven.
    fin = financials(cash=291_337_000, securities=2_062_579_000)

    liquidity, note = available_liquidity(fin)

    assert liquidity["value"] == 2_353_916_000
    assert "cash plus marketable securities" in note


def test_liquidity_will_not_add_figures_from_different_dates():
    # Recursion's last securities figure is from 2022 against cash from 2026.
    # they stopped reporting the tag, so adding it would invent money that was
    # spent years ago.
    fin = financials(cash=545_683_000, cash_as_of="2026-06-30",
                     securities=404_613_000, securities_as_of="2022-12-31")

    liquidity, note = available_liquidity(fin)

    assert liquidity["value"] == 545_683_000
    assert "left out" in note
    assert "2022-12-31" in note


def test_liquidity_is_just_cash_when_no_securities_are_reported():
    liquidity, note = available_liquidity(financials(cash=500))

    assert liquidity["value"] == 500
    assert note is None


def test_liquidity_is_none_without_cash():
    assert available_liquidity(financials(securities=100)) == (None, None)


def test_runway_is_computed_from_liquidity_not_cash():
    # the CRSP case end to end: 0.84 years on cash alone, 6.8 on what it holds
    fin = financials(cash=291_337_000, securities=2_062_579_000,
                     operating_cash_flow=-345_014_000)

    signal = assess_financials(fin)

    assert "~6.8 years" in " ".join(signal["evidence"])
    assert signal["label"] == "comfortable cash relative to burn"


def test_runway_falls_back_to_cash_when_securities_are_stale():
    fin = financials(cash=545_683_000, cash_as_of="2026-06-30",
                     securities=404_613_000, securities_as_of="2022-12-31",
                     operating_cash_flow=-371_808_000)

    signal = assess_financials(fin)

    # 545.7 / 371.8, not the 2.55 that adding the stale securities would give
    assert "~1.5 years" in " ".join(signal["evidence"])


def test_the_runway_note_says_whether_securities_were_included():
    combined = assess_financials(financials(cash=100, securities=100,
                                            operating_cash_flow=-100))
    cash_only = assess_financials(financials(cash=100, operating_cash_flow=-100))

    assert "most recent liquidity /" in " ".join(combined["evidence"])
    assert "most recent cash /" in " ".join(cash_only["evidence"])


# - debt

def test_debt_is_reported_and_flagged_as_outside_the_runway():
    # runway answers "how long can this be funded", not "what is left over", so
    # debt is stated rather than netted off
    signal = assess_financials(financials(cash=1000, operating_cash_flow=-100,
                                          debt=586_198_000))
    evidence = " ".join(signal["evidence"])

    assert "Debt: $586,198,000" in evidence
    assert "does not account for" in evidence


def test_stale_debt_says_it_may_no_longer_be_outstanding():
    # Fate's last debt figure is from 2018 against cash from 2026. a company that
    # repaid its borrowing simply stops reporting the tag, so the old number sits
    # in the record forever.
    signal = assess_financials(financials(
        cash=39_570_000, cash_as_of="2026-03-31", operating_cash_flow=-100,
        debt=18_480_000, debt_as_of="2018-12-31"))
    evidence = " ".join(signal["evidence"])

    assert "older than the cash figure" in evidence
    assert "repaid or refinanced" in evidence


def test_current_debt_carries_no_staleness_caveat():
    signal = assess_financials(financials(
        cash=291_337_000, cash_as_of="2026-06-30", operating_cash_flow=-100,
        debt=586_198_000, debt_as_of="2026-06-30"))

    assert "repaid or refinanced" not in " ".join(signal["evidence"])


def test_no_debt_line_when_none_is_reported():
    signal = assess_financials(financials(cash=1000, operating_cash_flow=-100))

    assert "Debt:" not in " ".join(signal["evidence"])


def test_zero_debt_is_not_reported_as_a_debt_line():
    signal = assess_financials(financials(cash=1000, operating_cash_flow=-100,
                                          debt=0))

    assert "Debt:" not in " ".join(signal["evidence"])


# - burn: the denominator of runway

def test_burn_prefers_operating_cash_flow_over_rd():
    # R&D is not a cash figure: it excludes G&A and includes non-cash charges,
    # so it is not the amount of money that left the company
    fin = financials(rd=100, operating_cash_flow=-250)

    assert annual_burn(fin) == (250, "operating cash flow")


def test_real_burn_can_be_lower_than_rd_expense():
    # the direction is not fixed. Recursion's R&D is $475m against $372m of cash
    # actually used, because R&D carries non-cash charges, so treating R&D as a
    # conservative stand-in would be wrong.
    fin = financials(rd=475_271_000, operating_cash_flow=-371_808_000)

    assert annual_burn(fin)[0] == 371_808_000


def test_burn_reads_the_magnitude_of_a_negative_cash_flow():
    # SEC reports cash used by operations as a negative number
    assert annual_burn(financials(operating_cash_flow=-187_048_000))[0] == \
        187_048_000


def test_a_company_generating_cash_has_no_burn():
    # positive operating cash flow means the business funds itself, so there is
    # no balance running down and no runway to estimate
    assert annual_burn(financials(operating_cash_flow=50, cash=1000)) == \
        (None, "operating cash flow")


def test_burn_falls_back_to_rd_when_cash_flow_is_missing():
    assert annual_burn(financials(rd=100)) == (100, "R&D expense")


def test_burn_is_none_when_nothing_was_reported():
    assert annual_burn(financials(cash=500)) == (None, None)


def test_zero_rd_is_not_a_usable_burn():
    assert annual_burn(financials(rd=0))[0] is None


def test_runway_uses_real_burn_not_rd():
    # 1000 cash against 250 of real burn is 4 years, not the 10 that dividing by
    # R&D alone would suggest. this is the direction that matters: R&D-only burn
    # makes every company look longer-lived than it is.
    signal = assess_financials(
        financials(rd=100, cash=1000, operating_cash_flow=-250))
    evidence = " ".join(signal["evidence"])

    assert "~4.0 years at the last full year's burn" in evidence
    assert "most recent cash / operating cash flow" in evidence
    assert signal["label"] == "comfortable cash relative to burn"


def test_the_weaker_fallback_says_it_is_weaker():
    # a runway built on R&D expense should not read the same as one built on the
    # real number, and the caveat must not claim a direction it can't know
    signal = assess_financials(financials(rd=100, cash=1000))
    evidence = " ".join(signal["evidence"])

    assert "R&D is not cash spent" in evidence
    assert "off in either direction" in evidence


def test_a_real_burn_runway_carries_no_such_warning():
    signal = assess_financials(
        financials(cash=1000, operating_cash_flow=-250))

    assert "R&D is not cash spent" not in " ".join(signal["evidence"])


def test_cash_generative_companies_get_their_own_label():
    signal = assess_financials(
        financials(cash=1000, operating_cash_flow=200, revenue=5000))

    assert signal["label"] == "cash generative"
    assert "runway estimate does not apply" in " ".join(signal["evidence"])


def test_cash_flow_evidence_is_signed_the_way_a_reader_expects():
    used = assess_financials(financials(operating_cash_flow=-187_048_000))
    made = assess_financials(financials(operating_cash_flow=200))

    assert "Cash used in operations: $187,048,000" in " ".join(used["evidence"])
    assert "Cash from operations: $200" in " ".join(made["evidence"])


# - revenue: which kind of company this is

def test_revenue_marks_a_commercial_stage_company():
    signal = assess_financials(financials(revenue=14_143_000))

    assert "Revenue: $14,143,000" in " ".join(signal["evidence"])
    assert "commercial-stage" in " ".join(signal["evidence"])


def test_zero_revenue_is_reported_as_pre_revenue():
    # a reported zero is a real finding, not missing data
    signal = assess_financials(financials(revenue=0))

    assert "pre-revenue" in " ".join(signal["evidence"])


def test_unreported_revenue_makes_no_claim_either_way():
    # nothing filed is not the same as filing a zero
    signal = assess_financials(financials(rd=100, cash=200))
    evidence = " ".join(signal["evidence"])

    assert "pre-revenue" not in evidence
    assert "commercial-stage" not in evidence


# - build_assessment

def test_assessment_bundles_both_signals_and_the_disclaimer():
    assessment = build_assessment(
        "Alpha Therapeutics",
        pipeline(total=1, active=1, by_phase={"PHASE3": 1}),
        financials(rd=100, cash=1000),
    )
    assert assessment["company"] == "Alpha Therapeutics"
    assert assessment["pipeline_signal"]["label"] == "advancing pipeline"
    assert assessment["financial_signal"]["label"] == \
        "comfortable cash relative to burn"
    # the app must never present itself as investment advice
    assert "not investment advice" in assessment["disclaimer"].lower()
