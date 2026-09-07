"""
These are the tests for the currency a figure was reported in.

They exist because the bug they cover was invisible: XBRL keys every fact by
unit, the parser dropped the key, and Novo Nordisk's DKK 26,464,000,000 of cash
sat in the same column as Amgen's dollars, printed with a dollar sign, cleared a
"over a billion in cash" filter on the exchange rate, and topped a ranking by
cash with a holding about a fifth of Amgen's. Nothing failed, no number looked
wrong, and 56 companies in this universe report cash in something other than
dollars.

So these tests are less about formatting than about refusing to compare. The
rule they hold down is that a figure in one currency is never ranked against,
added to, divided by or filtered against a figure in another, and that a unit
nobody recorded is not quietly treated as dollars. Run them with pytest.
"""

from app.analysis import annual_burn, available_liquidity, burn_figure
from app.changes import financial_changes
from app.data_sources import _entries_for, _latest_balance
from app.retrieval import query_companies
from app.units import is_dollars, millions, money, name_of, same_unit

from conftest import add_company


def tickers(results):
    return [r["ticker"] for r in results]


def figure(value, unit, period_end="2025-12-31"):
    """One stored figure, the shape every layer here passes around."""
    return {"value": value, "fiscal_year": 2025, "fiscal_period": "FY",
            "period_end": period_end, "unit": unit}


# - writing a figure down

def test_a_dollar_figure_keeps_the_dollar_sign():
    assert money(13_989_000_000, "USD") == "$13,989,000,000"
    assert millions(13_989_000_000, "USD") == "$13,989M"


def test_an_unambiguous_symbol_is_used_and_an_ambiguous_one_is_not():
    # yen has one symbol; "kr" is Danish, Swedish and Norwegian krone at once,
    # so the code carries it instead
    assert millions(385_113_000_000, "JPY") == "¥385,113M"
    assert millions(26_464_000_000, "DKK") == "DKK 26,464M"


def test_the_currency_can_be_spelled_out_where_a_figure_stands_alone():
    assert millions(26_464_000_000, "DKK", name=True) == "DKK 26,464M (Danish kroner)"
    # dollars need no gloss, and one on every row of a table would bury them
    assert millions(13_989_000_000, "USD", name=True) == "$13,989M"


def test_a_missing_unit_says_so_rather_than_borrowing_a_dollar_sign():
    assert money(500, None) == "500 (unit not recorded)"
    assert name_of(None) == "an unrecorded unit"


def test_a_share_count_is_not_money():
    assert money(3_200_000, "shares") == "3,200,000 shares"


def test_an_unknown_code_is_still_written_truthfully():
    # a currency this universe has not filed in yet keeps its code, which is
    # true, rather than being dropped or guessed at
    assert money(1_000, "XYZ") == "XYZ 1,000"
    assert name_of("XYZ") == "XYZ"


def test_only_dollars_are_dollars():
    assert is_dollars("USD")
    assert not is_dollars("DKK")
    # the row that predates the column is unknown, not American
    assert not is_dollars(None)


# - what the parser carries out of an XBRL response

def test_every_reported_unit_reaches_the_selector_with_its_key():
    facts = {"facts": {"us-gaap": {"CashAndCashEquivalentsAtCarryingValue": {
        "units": {
            "USD": [{"val": 1, "end": "2025-12-31", "form": "10-K"}],
            "DKK": [{"val": 2, "end": "2025-12-31", "form": "10-K"}],
        }}}}}

    entries = _entries_for(facts, "CashAndCashEquivalentsAtCarryingValue")

    assert {e["unit"] for e in entries} == {"USD", "DKK"}


def test_a_company_reporting_one_period_in_two_units_is_read_in_dollars():
    # dual reporting happens, and the dollar figure is the one comparable to
    # every other company here, so it wins a tie on the same period and filing
    facts = {"facts": {"us-gaap": {"CashAndCashEquivalentsAtCarryingValue": {
        "units": {
            "DKK": [{"val": 26_464, "end": "2025-12-31", "form": "10-K",
                     "filed": "2026-02-01", "fy": 2025, "fp": "FY"}],
            "USD": [{"val": 3_900, "end": "2025-12-31", "form": "10-K",
                     "filed": "2026-02-01", "fy": 2025, "fp": "FY"}],
        }}}}}

    best = _latest_balance(facts, ["CashAndCashEquivalentsAtCarryingValue"])

    assert best["unit"] == "USD"
    assert best["value"] == 3_900


# - filtering

def test_a_dollar_threshold_does_not_judge_a_figure_in_another_currency(db):
    add_company(db, "USA", "Dollar Bio", trials=[("PHASE3", "RECRUITING")],
                rd=100_000_000, cash=2_000_000_000)
    # 26.46bn kroner is about 3.9bn dollars, but the number alone clears a
    # dollar threshold for the wrong reason and would fail a bigger one for the
    # wrong reason too
    add_company(db, "DKA", "Kroner Bio", trials=[("PHASE3", "RECRUITING")],
                rd=100_000_000, cash=26_464_000_000, unit="DKK")

    assert tickers(query_companies(db, min_cash=1_000_000_000)) == ["USA"]


def test_a_row_with_no_recorded_unit_is_not_treated_as_dollars(db):
    add_company(db, "UNK", "Unknown Unit Bio", trials=[("PHASE1", "RECRUITING")],
                cash=5_000_000_000, unit=None)

    assert tickers(query_companies(db, min_cash=1_000_000_000)) == []


def test_the_companies_a_dollar_threshold_could_not_judge_are_reported(db):
    add_company(db, "USA", "Dollar Bio", cash=2_000_000_000)
    add_company(db, "DKA", "Kroner Bio", cash=26_464_000_000, unit="DKK")
    add_company(db, "JPA", "Yen Bio", cash=385_113_000_000, unit="JPY")

    set_aside = []
    query_companies(db, min_cash=1_000_000_000, not_in_dollars=set_aside)

    # named, because "one company matches" is a different claim if two were
    # never compared at all
    assert sorted(set(set_aside)) == ["DKA", "JPA"]


# - ranking

def test_a_ranking_by_money_ranks_dollars_and_leaves_the_rest_unranked(db):
    add_company(db, "BIG", "Big Dollar Bio", cash=13_989_000_000)
    add_company(db, "SML", "Small Dollar Bio", cash=1_000_000_000)
    # the largest number in the table and about a fifth of BIG's holding
    add_company(db, "JPA", "Yen Bio", cash=385_113_000_000, unit="JPY")

    ranked = tickers(query_companies(db, sort_by="cash"))

    assert ranked[:2] == ["BIG", "SML"]
    assert ranked[-1] == "JPA"


def test_a_ranking_by_money_says_which_companies_it_could_not_place(db):
    add_company(db, "BIG", "Big Dollar Bio", cash=13_989_000_000)
    add_company(db, "JPA", "Yen Bio", cash=385_113_000_000, unit="JPY")

    set_aside = []
    query_companies(db, sort_by="cash", not_in_dollars=set_aside)

    assert set(set_aside) == {"JPA"}


def test_ranking_by_a_count_is_unaffected_by_currency(db):
    # trials are trials in every country, so nothing here should touch them
    add_company(db, "JPA", "Yen Bio", trials=[("PHASE3", "RECRUITING")] * 3,
                cash=385_113_000_000, unit="JPY")
    add_company(db, "USA", "Dollar Bio", trials=[("PHASE1", "RECRUITING")],
                cash=1_000_000_000)

    assert tickers(query_companies(db, sort_by="active_trials")) == ["JPA", "USA"]


# - arithmetic that only works within one currency

def test_securities_in_another_currency_are_not_added_to_cash():
    liquidity, note = available_liquidity({
        "cash": figure(1_000_000_000, "USD"),
        "marketable_securities": figure(2_000_000_000, "DKK"),
    })

    assert liquidity["value"] == 1_000_000_000
    assert "different unit" in note


def test_securities_in_the_same_currency_and_period_still_add():
    liquidity, note = available_liquidity({
        "cash": figure(1_000_000_000, "DKK"),
        "marketable_securities": figure(2_000_000_000, "DKK"),
    })

    assert liquidity["value"] == 3_000_000_000
    assert "DKK 3,000,000,000" in note


def test_a_burn_and_a_balance_in_different_units_do_not_make_a_ratio():
    fin = {"cash": figure(1_000_000_000, "USD"),
           "operating_cash_flow": figure(-100_000_000, "DKK")}

    liquidity, _ = available_liquidity(fin)
    burn, _ = annual_burn(fin)

    assert burn and liquidity
    # both figures exist and the division is still refused, because the answer
    # would be a number of nothing
    assert not same_unit(liquidity, burn_figure(fin))


# - comparing two snapshots

def test_a_change_of_reporting_currency_is_not_reported_as_a_change_in_figures():
    before = {"cash": figure(26_464_000_000, "DKK")}
    after = {"cash": figure(3_900_000_000, "USD", period_end="2026-12-31")}

    changes = financial_changes(before, after)

    # an 85% fall would be the arithmetic; what happened is a relabelling
    assert [c["kind"] for c in changes] == ["unit_changed"]
    assert changes[0]["change"] is None
    assert "DKK" in changes[0]["detail"] and "USD" in changes[0]["detail"]


def test_a_real_change_in_the_same_currency_is_still_reported():
    before = {"cash": figure(1_000_000_000, "USD")}
    after = {"cash": figure(2_000_000_000, "USD", period_end="2026-12-31")}

    changes = financial_changes(before, after)

    assert [c["kind"] for c in changes] == ["figure_changed"]
    assert changes[0]["change"] == 1.0
