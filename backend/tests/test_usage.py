"""
The daily ceiling on /ask.

This is the only thing standing between a public URL and an unbounded OpenAI
bill, so the properties worth pinning are the ones that fail silently: that two
requests arriving together cannot both take the last slot, that a refused
question does not consume budget it was never given, and that the count is per
UTC day rather than per process.
"""

import datetime

import pytest

from app import usage
from app.models import Base


@pytest.fixture
def budgeted(db, monkeypatch):
    """A database with the budget table, and a small ceiling to reach."""
    Base.metadata.create_all(db.get_bind(), tables=[usage.AskBudget.__table__])
    monkeypatch.setenv("ASK_DAILY_BUDGET", "3")
    return db


def test_the_budget_runs_out(budgeted):
    got = [usage.claim_question(budgeted)[0] for _ in range(5)]

    assert got == [True, True, True, False, False]


def test_a_refused_question_costs_nothing(budgeted):
    for _ in range(6):
        usage.claim_question(budgeted)

    # three answered, three refused: the count is questions answered, not
    # questions attempted, or a page showing it climbs all day after the
    # budget is gone
    held = budgeted.query(usage.AskBudget).one()
    assert held.questions == 3


def test_each_day_starts_again(budgeted):
    day = datetime.date(2026, 9, 5)
    for _ in range(4):
        usage.claim_question(budgeted, day=day)

    allowed, used, _ = usage.claim_question(budgeted, day=day + datetime.timedelta(days=1))

    assert allowed
    assert used == 1


def test_no_ceiling_when_it_is_turned_off(budgeted, monkeypatch):
    monkeypatch.setenv("ASK_DAILY_BUDGET", "0")

    assert all(usage.claim_question(budgeted)[0] for _ in range(50))
    # and nothing is written, because there is nothing to count against
    assert budgeted.query(usage.AskBudget).count() == 0


def test_an_unreadable_ceiling_is_the_default_not_none(monkeypatch):
    # the failure to avoid is a typo in an environment variable turning the cap
    # off rather than turning it strict
    monkeypatch.setenv("ASK_DAILY_BUDGET", "five hundred")

    assert usage.budget_limit() == usage.DEFAULT_BUDGET


def test_the_refusal_says_what_still_works(budgeted):
    body = usage.refusal(3, 3)

    assert body["unavailable"] is True
    assert body["budget"] == {"used": 3, "limit": 3, "resets": body["budget"]["resets"]}
    # a refusal that only says no is an error message with better manners
    assert "watchlist" in body["answer"]
    assert body["budget"]["resets"] > usage.today().isoformat()
