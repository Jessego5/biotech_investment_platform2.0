"""
This file holds the shared test fixtures. The database tests run against a fresh
in-memory SQLite built from the real schema, not backend/biotech.db, so they never
read or write the ingested data and every test starts from a universe we defined
ourselves. pytest picks this file up on its own, there is nothing to import.
"""

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Company, Trial, Financial


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """
    Fail any test that tries to make a real request. The suite is meant to run
    offline, and the way that quietly stops being true is a test stubbing one
    lookup and forgetting its neighbour: nothing fails, the call just goes to the
    live API and the suite gets slower and flakier. This turns that into an error.
    """
    def blocked(*args, **kwargs):
        raise AssertionError(
            "a test made a real HTTP request. stub the fetch it needs.")

    monkeypatch.setattr(requests, "get", blocked)
    monkeypatch.setattr(requests, "post", blocked)


@pytest.fixture
def db():
    """An empty in-memory database with the real schema."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


def add_company(db, ticker, name, sector=None, trials=(), rd=None, cash=None,
                fiscal_year=2024, cash_as_of=None, trial_count_total=None,
                trials_truncated=False):
    """
    Seed one company. trials is a list of (phase, status) pairs, rd and cash are
    plain numbers, and either can be left off to model a company whose financials
    never came back from EDGAR.

    The two metrics are stored with different periods, the way ingestion writes
    them: R&D covers a full year, cash is a balance on a date and usually comes
    from a more recent quarterly filing.
    """
    company = Company(ticker=ticker, name=name, sector=sector,
                      trial_count_total=trial_count_total,
                      trials_truncated=trials_truncated)
    # give each trial a distinct NCT id so the rows are distinguishable
    for i, (phase, status) in enumerate(trials):
        company.trials.append(Trial(
            nct_id=f"NCT{ticker}{i:04d}", title=f"{name} trial {i}",
            phase=phase, status=status, lead_sponsor=name, summary="",
        ))
    # only store the metrics that were actually given, the same way ingest does
    year_end = f"{fiscal_year}-12-31"
    periods = {
        "rd_expense": ("FY", year_end),
        "cash": ("Q2", cash_as_of or year_end),
    }
    for metric, value in (("rd_expense", rd), ("cash", cash)):
        if value is not None:
            fiscal_period, period_end = periods[metric]
            company.financials.append(Financial(
                metric=metric, value=value, fiscal_year=fiscal_year,
                fiscal_period=fiscal_period, period_end=period_end))
    db.add(company)
    db.commit()
    return company


@pytest.fixture
def universe(db):
    """
    A small but varied universe covering the cases the filters care about:
    late-stage vs early-stage, rich vs tight cash, and missing financials.
    """
    # late-stage, comfortable cash (runway 10.0)
    add_company(db, "AAA", "Alpha Therapeutics", sector="biotech",
                trials=[("PHASE3", "RECRUITING"), ("PHASE1", "COMPLETED")],
                rd=100_000_000, cash=1_000_000_000)
    # early-stage only, tight cash (runway 0.5)
    add_company(db, "BBB", "Beta Biosciences", sector="biotech",
                trials=[("PHASE1", "RECRUITING"), ("PHASE2", "TERMINATED")],
                rd=200_000_000, cash=100_000_000)
    # no trials at all and no financials stored
    add_company(db, "CCC", "Gamma Pharma", sector="pharma")
    return db
