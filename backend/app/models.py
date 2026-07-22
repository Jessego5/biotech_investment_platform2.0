"""
These are the database models for the biotech universe. It runs on SQLite for
dev but uses plain SQLAlchemy so it can move to Postgres later. Every row carries
timestamps. For now we only keep the current snapshot, but keeping fetched_at and
updated_at means we can store several snapshots later without a redesign, which is
what makes monitoring and backtesting possible down the road.
"""

from datetime import datetime, timezone

from sqlalchemy import (Column, Integer, Float, String, Text, LargeBinary,
                        DateTime, ForeignKey)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _now():
    # use timezone-aware UTC so the timestamps are never ambiguous
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = "companies"

    ticker = Column(String, primary_key=True)
    cik = Column(String)
    name = Column(String, nullable=False)
    sector = Column(String)          # coarse label taken from the SIC code it was sourced under
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    trials = relationship("Trial", back_populates="company",
                          cascade="all, delete-orphan")
    financials = relationship("Financial", back_populates="company",
                              cascade="all, delete-orphan")


class Trial(Base):
    __tablename__ = "trials"

    # use a surrogate id, not nct_id, as the primary key: the SAME NCT can belong
    # to more than one company (co-sponsored trials), and using nct_id as the PK
    # made those collide. a surrogate id also keeps us free to store the same
    # trial across multiple snapshots later.
    id = Column(Integer, primary_key=True, autoincrement=True)
    nct_id = Column(String, index=True)
    company_ticker = Column(String, ForeignKey("companies.ticker"))
    title = Column(String)
    phase = Column(String)
    status = Column(String)
    lead_sponsor = Column(String)
    # free text (summary, conditions, interventions, eligibility) that the
    # structured fields can't answer over, plus its embedding for semantic search.
    summary = Column(Text)
    embedding = Column(LargeBinary)   # the np.float32 vector stored as raw bytes
    fetched_at = Column(DateTime, default=_now)

    company = relationship("Company", back_populates="trials")


class Financial(Base):
    __tablename__ = "financials"

    # one row per metric per company (like "rd_expense" or "cash"). use a plain
    # id, not a composite key, so we can keep several snapshots of the same metric later.
    id = Column(Integer, primary_key=True, autoincrement=True)
    company_ticker = Column(String, ForeignKey("companies.ticker"))
    metric = Column(String)          # either "rd_expense" or "cash"
    value = Column(Float)
    fiscal_year = Column(Integer)
    fetched_at = Column(DateTime, default=_now)

    company = relationship("Company", back_populates="financials")
