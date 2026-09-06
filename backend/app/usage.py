"""
This is the daily ceiling on what answering questions can cost. /ask is the one
endpoint that spends money and everything else costs a query, and since there are
no accounts there is nobody to bill and nobody to throttle individually, so the
only limit that actually holds is one counted where the spend happens, for
everyone at once. It lives in the database rather than in the process, because a
counter in memory resets on every deploy and two tasks behind a load balancer
each keep their own, so the cap you set would quietly become twice the cap or
none at all after a crash loop, and raising DesiredCount is the first thing
DEPLOY.md says to do. The claim is a single statement rather than a read and then
a write, so two requests arriving together cannot both take the last slot, and a
refused question is never counted, since the number is questions answered and not
questions attempted. The ceiling is a refusal and not an error: the system can
say what it did and what it can no longer do, which is a designed state. Imported
by main.py, and the limit is read from ASK_DAILY_BUDGET at call time, defaulting
to 500 and switched off by 0.
"""

import datetime
import os

from sqlalchemy import Column, Integer, String, text

from .models import Base

# Measured against the shape of a question rather than guessed: three rounds of
# tool calls with nine schemas resent each time, six passages of about 3,000
# characters accumulating in the history, then the answer call, roughly 31,000
# input tokens at the worst, well under half a cent. 500 is therefore a ceiling
# of a couple of dollars on the worst possible day, and far less on a real one.
DEFAULT_BUDGET = 500


class AskBudget(Base):
    """
    One row per UTC day. Nothing is stored about who asked, the row is a
    count, and a count is not a record of anybody.
    """
    __tablename__ = "ask_budget"

    day = Column(String, primary_key=True)      # ISO date, UTC
    questions = Column(Integer, nullable=False, default=0)


def budget_limit():
    """
    Questions allowed per UTC day.

    Read at call time rather than at import, so the deployed service can be
    given a different ceiling without a new image. Zero or less turns the cap
    off, which is what a local run wants and why the tests need no environment.
    """
    raw = os.environ.get("ASK_DAILY_BUDGET", "").strip()
    if not raw:
        return DEFAULT_BUDGET
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_BUDGET


def today():
    return datetime.datetime.now(datetime.timezone.utc).date()


def claim_question(db, day=None):
    """
    Take one question out of today's budget, or report that there is none left.

    Returns (allowed, used, limit).

    One statement, because two would be a race: read-then-write lets two
    requests arriving together both see room and both take the last slot. The
    WHERE on the conflict branch means the row is only incremented while it is
    under the ceiling, so a refused question costs nothing, the count is
    questions answered, not questions attempted, and a page showing it would
    otherwise climb all day after the budget ran out.
    """
    limit = budget_limit()
    day = (day or today()).isoformat()
    if limit <= 0:
        return True, 0, limit

    row = db.execute(text(
        "INSERT INTO ask_budget (day, questions) VALUES (:day, 1) "
        "ON CONFLICT (day) DO UPDATE SET questions = ask_budget.questions + 1 "
        "WHERE ask_budget.questions < :limit "
        "RETURNING questions"), {"day": day, "limit": limit}).first()
    db.commit()

    if row is None:
        return False, limit, limit
    return True, row[0], limit


def spent_message(limit, resets):
    """
    What the reader is told. It says what ran out, when it comes back, and what
    still works, the same three things any refusal here owes them.
    """
    return (
        f"Today's budget for answering questions is spent: {limit} since "
        f"00:00 UTC. It comes back at 00:00 UTC on {resets}.\n\n"
        "Nothing else is affected. Browse, the company pages and the watchlist "
        "read the corpus directly and cost nothing to serve, so every figure "
        "and every filing is still there to open."
    )


def refusal(used, limit):
    """The body /ask returns once the day's budget is gone."""
    resets = (today() + datetime.timedelta(days=1)).isoformat()
    return {
        "answer": spent_message(limit, resets),
        "sources": [],
        "unavailable": True,
        "budget": {"used": used, "limit": limit, "resets": resets},
    }
