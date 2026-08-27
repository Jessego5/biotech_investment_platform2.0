"""
These are the tests for the shared retrieval layer. Both /companies and the chat
answer through query_companies, so a filter bug here is not just a wrong list, it
is a wrong answer in the chat too, phrased confidently. They cover every filter,
sort key, and limit, and they run against a seeded in-memory database rather than
biotech.db, so the universe under test is known and the real data is never
touched. Run them with pytest.
"""

import pytest

from app.retrieval import (trials_from_db, financials_from_db, late_stage_count,
                           query_companies, company_facts)

from conftest import add_company


def tickers(results):
    return [r["ticker"] for r in results]


# - row flattening

def test_trials_from_db_flattens_the_stored_rows(db):
    company = add_company(db, "AAA", "Alpha",
                          trials=[("PHASE3", "RECRUITING")])

    trials = trials_from_db(company)

    # the row carries what it treats and when it reports as well, and null is
    # what an un-ingested field looks like rather than an absent one
    assert trials == [{"nct_id": "NCTAAA0000", "title": "Alpha trial 0",
                       "phase": "PHASE3", "status": "RECRUITING",
                       "lead_sponsor": "Alpha", "role": None,
                       "conditions": None, "completion_date": None,
                       "completion_date_type": None, "enrollment": None,
                       "has_results": None}]


def test_financials_from_db_rebuilds_the_shape_analysis_expects(db):
    company = add_company(db, "AAA", "Alpha", rd=100, cash=500, fiscal_year=2023)

    fins = financials_from_db(company)

    assert fins["available"] is True
    assert fins["rd_expense"]["value"] == 100
    assert fins["cash"]["value"] == 500
    # each figure says which period it covers, because they are not the same kind
    # of number: a year's spending versus a balance on a date
    assert fins["rd_expense"]["fiscal_period"] == "FY"
    assert fins["cash"]["period_end"] == "2023-12-31"


def test_financials_from_db_says_unavailable_rather_than_showing_zero(db):
    company = add_company(db, "CCC", "Gamma")

    fins = financials_from_db(company)

    assert fins["available"] is False
    assert "no financials stored" in fins["reason"]


def test_financials_are_returned_as_ints_not_floats(db):
    # the column is a Float, but the app formats these with a thousands
    # separator, so they must come back out as whole numbers
    company = add_company(db, "AAA", "Alpha", rd=1_500_000, cash=9_000_000)

    fins = financials_from_db(company)

    assert isinstance(fins["rd_expense"]["value"], int)
    assert fins["rd_expense"]["value"] == 1_500_000


def test_financials_from_db_handles_only_one_metric_stored(db):
    company = add_company(db, "AAA", "Alpha", rd=100)

    fins = financials_from_db(company)

    assert fins["available"] is True
    assert fins["cash"] is None


# - late_stage_count

def test_late_stage_count_covers_phase3_phase4_and_combined_strings():
    by_phase = {"PHASE1": 5, "PHASE2": 3, "PHASE3": 2, "PHASE4": 1,
                "PHASE2, PHASE3": 4, "N/A": 7}
    # 2 + 1 + 4, and nothing from the early phases or the unknowns
    assert late_stage_count(by_phase) == 7


def test_late_stage_count_of_an_early_stage_pipeline_is_zero():
    assert late_stage_count({"PHASE1": 5, "PHASE2": 3, "N/A": 1}) == 0


# - query_companies filters

def test_no_filters_returns_the_whole_universe_sorted_by_ticker(universe):
    assert tickers(query_companies(universe)) == ["AAA", "BBB", "CCC"]


def test_min_rd_excludes_companies_with_no_financials(universe):
    # CCC has no R&D figure at all, so it cannot satisfy a minimum
    assert tickers(query_companies(universe, min_rd=1)) == ["AAA", "BBB"]


def test_min_rd_filters_on_the_real_value(universe):
    assert tickers(query_companies(universe, min_rd=150_000_000)) == ["BBB"]


def test_min_cash_filters_on_the_real_value(universe):
    assert tickers(query_companies(universe, min_cash=500_000_000)) == ["AAA"]


def test_has_phase3_true_keeps_only_late_stage_companies(universe):
    assert tickers(query_companies(universe, has_phase3=True)) == ["AAA"]


def test_has_phase3_false_keeps_only_companies_without_late_stage(universe):
    # this must include CCC, which has no trials at all
    assert tickers(query_companies(universe, has_phase3=False)) == ["BBB", "CCC"]


def test_has_phase3_none_does_not_filter(universe):
    assert len(query_companies(universe, has_phase3=None)) == 3


def test_min_active_trials_filters_on_the_running_pipeline(universe):
    # AAA and BBB each have exactly one recruiting trial
    assert tickers(query_companies(universe, min_active_trials=1)) == ["AAA", "BBB"]
    assert tickers(query_companies(universe, min_active_trials=2)) == []


def test_sector_match_is_case_insensitive(universe):
    assert tickers(query_companies(universe, sector="BioTech")) == ["AAA", "BBB"]


def test_min_runway_filters_on_cash_over_burn(universe):
    # AAA is 10.0x, BBB is 0.5x
    assert tickers(query_companies(universe, min_runway=1)) == ["AAA"]


def test_min_runway_excludes_companies_with_no_computable_runway(universe):
    # CCC has neither figure, so it is never "above" a runway threshold
    assert "CCC" not in tickers(query_companies(universe, min_runway=0))


def test_min_runway_uses_the_exact_value_not_the_rounded_one(db):
    # 998/1000 is 0.998, which rounds to 1.0 for display. filtering on the
    # rounded value would wrongly include it at a 1.0 minimum.
    add_company(db, "AAA", "Alpha", rd=1000, cash=998)

    assert query_companies(db, min_runway=1.0) == []
    # but it is still displayed rounded
    assert query_companies(db)[0]["runway"] == 1.0


def test_filters_are_anded_together(universe):
    # late-stage AND well-capitalized leaves only AAA; adding an impossible
    # R&D floor leaves nothing
    assert tickers(query_companies(universe, has_phase3=True,
                                   min_cash=500_000_000)) == ["AAA"]
    assert query_companies(universe, has_phase3=True,
                           min_rd=10_000_000_000) == []


# - query_companies output, sorting and limit

def test_summary_rows_carry_the_fields_the_frontend_renders(universe):
    row = next(r for r in query_companies(universe) if r["ticker"] == "AAA")

    assert row["name"] == "Alpha Therapeutics"
    assert row["sector"] == "biotech"
    assert row["total_trials"] == 2
    assert row["active_trials"] == 1
    assert row["has_phase3"] is True
    assert row["rd_expense"]["value"] == 100_000_000
    assert row["runway"] == 10.0


def test_a_company_with_no_data_still_returns_a_complete_row(universe):
    row = next(r for r in query_companies(universe) if r["ticker"] == "CCC")

    # missing data is None, never a fabricated zero
    assert row["total_trials"] == 0
    assert row["has_phase3"] is False
    assert row["rd_expense"] is None
    assert row["cash"] is None
    assert row["runway"] is None


def test_a_truncated_pipeline_says_how_many_there_really_are(db):
    # a large sponsor registers more trials than one run will fetch. showing the
    # fetched count alone would present part of a pipeline as the whole thing.
    add_company(db, "PFE", "Pfizer", trials=[("PHASE3", "RECRUITING")],
                trial_count_total=6061, trials_truncated=True)

    row = query_companies(db)[0]

    assert row["total_trials"] == 1
    assert row["total_trials_reported"] == 6061
    assert row["trials_truncated"] is True


def test_a_complete_pipeline_is_not_flagged(universe):
    row = next(r for r in query_companies(universe) if r["ticker"] == "AAA")

    assert row["trials_truncated"] is False


def test_company_facts_carry_the_truncation_too(db):
    # the detail view is where someone reads the pipeline closely, so it needs
    # this more than the list does
    add_company(db, "PFE", "Pfizer", trials=[("PHASE3", "RECRUITING")],
                trial_count_total=6061, trials_truncated=True)

    pipeline = company_facts(db, "PFE")["pipeline"]

    assert pipeline["total_trials"] == 1
    assert pipeline["total_trials_reported"] == 6061
    assert pipeline["truncated"] is True


@pytest.mark.parametrize("sort_by, expected_first", [
    ("rd", "BBB"),            # BBB spends more on R&D
    ("cash", "AAA"),
    ("runway", "AAA"),
    ("total_trials", "AAA"),
])
def test_sorting_is_descending_for_most_and_highest_questions(
        universe, sort_by, expected_first):
    assert tickers(query_companies(universe, sort_by=sort_by))[0] == expected_first


def test_companies_with_missing_values_sort_last(universe):
    # CCC has no cash figure and must not outrank companies that do
    assert tickers(query_companies(universe, sort_by="cash"))[-1] == "CCC"


def test_an_unknown_sort_key_falls_back_to_ticker_order(universe):
    assert tickers(query_companies(universe, sort_by="nonsense")) == \
        ["AAA", "BBB", "CCC"]


def test_limit_caps_the_results_after_sorting(universe):
    assert tickers(query_companies(universe, sort_by="cash", limit=1)) == ["AAA"]


def test_limit_larger_than_the_universe_is_harmless(universe):
    assert len(query_companies(universe, limit=99)) == 3


# - company_facts

def test_company_facts_returns_the_full_grounded_bundle(universe):
    facts = company_facts(universe, "AAA")

    assert facts["ticker"] == "AAA"
    assert facts["name"] == "Alpha Therapeutics"
    assert facts["pipeline"]["total_trials"] == 2
    assert facts["financials"]["available"] is True
    assert facts["assessment"]["pipeline_signal"]["label"] == "advancing pipeline"


def test_company_facts_lookup_is_case_insensitive(universe):
    assert company_facts(universe, "aaa")["ticker"] == "AAA"


def test_company_facts_returns_none_for_a_company_not_in_the_db(universe):
    assert company_facts(universe, "ZZZ") is None


def test_company_facts_for_an_empty_company_is_honest(universe):
    facts = company_facts(universe, "CCC")

    assert facts["pipeline"]["total_trials"] == 0
    assert facts["financials"]["available"] is False
    assert facts["assessment"]["pipeline_signal"]["label"] == "no registered trials"
    assert facts["assessment"]["financial_signal"]["label"] == \
        "financials unavailable"
