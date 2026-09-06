"""
This tests the one index over everything held. The rule under test is that a hit
is a thing and not a row: both the products table and the trials table store the
same thing more than once, a drug once per dosage form and a co-sponsored study
once per company attached to it, and listing those rows straight gave a reader
the same trial twice with a different ticker on each, which reads as two studies.
"""

import pytest

from app import main
from app.models import Trial


@pytest.fixture
def search(db, monkeypatch):
    """search() opens its own session, so point that at the test database."""
    monkeypatch.setattr(main, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    return main.search


def _trial(nct, ticker, role="lead", title="RADAR"):
    return Trial(nct_id=nct, company_ticker=ticker, title=title,
                 phase="PHASE3", status="COMPLETED", role=role)


def test_a_co_sponsored_trial_is_one_hit(db, search):
    db.add_all([_trial("NCT00193856", "ABT"),
                _trial("NCT00193856", "NVSEF", role="collaborator")])
    db.commit()

    out = search(q="NCT00193856")

    assert out["counts"]["trial"] == 1
    assert [h["id"] for h in out["results"]] == ["NCT00193856"]


def test_both_sponsors_are_named(db, search):
    db.add_all([_trial("NCT00193856", "ABT"),
                _trial("NCT00193856", "NVSEF", role="collaborator")])
    db.commit()

    hit, = search(q="NCT00193856")["results"]

    # naming one of them would be a claim about who runs the study
    assert "ABT, NVSEF" in hit["meta"]


def test_the_lead_row_wins(db, search):
    # stored collaborator-first, so the choice cannot come from row order
    db.add_all([_trial("NCT00193856", "NVSEF", role="collaborator"),
                _trial("NCT00193856", "ABT", title="RADAR, as the lead holds it")])
    db.commit()

    hit, = search(q="NCT00193856")["results"]

    assert hit["title"] == "RADAR, as the lead holds it"


def test_the_cap_counts_trials_not_rows(db, search):
    # ten studies, each held twice: a cap applied to rows would show five
    for i in range(10):
        db.add_all([_trial(f"NCT0000000{i}", "ABT"),
                    _trial(f"NCT0000000{i}", "NVSEF", role="collaborator")])
    db.commit()

    out = search(q="NCT", limit=8)

    assert out["counts"]["trial"] == 8
    assert len({h["id"] for h in out["results"]}) == 8
