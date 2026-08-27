"""
These are the database models for the biotech universe. It runs on SQLite for
dev but uses plain SQLAlchemy so it can move to Postgres later, and the one place
the two databases really differ, the trial embedding, is handled by a column type
that stores whichever form each can search. Every row carries timestamps. For now
we only keep the current snapshot, but keeping fetched_at and updated_at means we
can store several snapshots later without a redesign, which is what makes
monitoring and backtesting possible down the road.
"""

from datetime import datetime, timezone

import numpy as np
from pgvector.sqlalchemy import Vector
from sqlalchemy import (Column, Integer, Float, String, Text, LargeBinary,
                        Boolean, DateTime, ForeignKey, TypeDecorator)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# how many numbers are in one trial's embedding. text-embedding-3-small returns
# 1536, and the column has to say so up front because Postgres wants the width
# in the type.
EMBEDDING_DIM = 1536


class Embedding(TypeDecorator):
    """
    A trial's embedding, stored the way each database can actually search it.

    On Postgres this is a real pgvector column, so nearest-neighbour search is a
    query the database answers. On SQLite there is no vector type, so it falls
    back to the raw float32 bytes it has always been, and search happens in
    memory. Either way the Python side just sees a vector, which keeps the code
    that writes and reads embeddings from caring which database it is talking to.

    This exists because the two are at different stages: SQLite is what runs
    locally today and holds the current 12,943 embedded trials, and Postgres is
    where this goes when the universe grows past what fits in memory.
    """

    impl = LargeBinary
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(EMBEDDING_DIM))
        return dialect.type_descriptor(LargeBinary())

    def process_bind_param(self, value, dialect):
        """Going in: a sequence of floats, however this database wants it."""
        if value is None:
            return None
        # pgvector takes the numbers themselves and handles the encoding
        if dialect.name == "postgresql":
            return list(value)
        return np.asarray(value, dtype=np.float32).tobytes()

    def process_result_value(self, value, dialect):
        """Coming out: always a float32 array, whatever it was stored as."""
        if value is None:
            return None
        if dialect.name == "postgresql":
            return np.asarray(value, dtype=np.float32)
        return np.frombuffer(value, dtype=np.float32)

    class comparator_factory(TypeDecorator.Comparator):
        def cosine_distance(self, other):
            """
            Postgres-only: the <=> operator, which is what makes the search a
            query rather than a full load into memory. Calling this on SQLite
            would produce SQL it cannot run, so the search layer checks the
            dialect before using it.
            """
            return self.op("<=>", return_type=Float)(other)


# the financial figures we keep, one Financial row per metric per company. this
# table is keyed by metric name rather than having a column per figure, so adding
# one here is the whole change: no migration, just more rows.
FINANCIAL_METRICS = ("rd_expense", "cash", "marketable_securities", "debt",
                     "operating_cash_flow", "net_income", "revenue",
                     "shares_outstanding")


def _now():
    # use timezone-aware UTC so the timestamps are never ambiguous
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = "companies"

    ticker = Column(String, primary_key=True)
    cik = Column(String)
    name = Column(String, nullable=False)
    sector = Column(String)          # coarse label taken from the SIC code it was sourced under
    # how many trials the sponsor really has, and whether we stopped short of
    # fetching them all. a handful of large sponsors register more studies than we
    # are willing to pull in one run, and without these the app would show a
    # partial pipeline as though it were the whole one.
    trial_count_total = Column(Integer)
    trials_truncated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    trials = relationship("Trial", back_populates="company",
                          cascade="all, delete-orphan")
    financials = relationship("Financial", back_populates="company",
                              cascade="all, delete-orphan")
    filings = relationship("Filing", back_populates="company",
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
    # a real vector column on Postgres, raw float32 bytes on SQLite; either way
    # Python reads and writes it as a plain sequence of numbers
    embedding = Column(Embedding)

    # What the trial is for, and when it reports. Both were being fetched and
    # thrown away, which left the pipeline able to say "Phase 3, recruiting" and
    # not "Phase 3, atopic dermatitis, reading out in Q2 2026" — the second being
    # the fact anyone actually wants.
    conditions = Column(Text, index=True)
    # a date carries whether it happened. An estimated completion is when a
    # readout is expected, an actual one is when it arrived, and reporting the
    # first as the second would invent the history this project exists to avoid.
    start_date = Column(String)
    start_date_type = Column(String)            # ACTUAL or ESTIMATED
    completion_date = Column(String, index=True)
    completion_date_type = Column(String)       # ACTUAL or ESTIMATED
    enrollment = Column(Integer)
    enrollment_type = Column(String)            # ACTUAL or ESTIMATED

    # How much weight the trial's evidence can carry. "Robust data" is a
    # judgement nobody can store, but the things it is made of are all recorded:
    # whether patients were randomised, whether anyone was blinded, and whether
    # results were ever posted. These are null on rows written before they were
    # collected, which is a real gap and not a claim that the trial lacked them.
    has_results = Column(Boolean)
    allocation = Column(String)                 # RANDOMIZED or NON_RANDOMIZED
    masking = Column(String)                    # NONE, SINGLE ... QUADRUPLE

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
    # which period the figure covers, and when that period ended. the two metrics
    # are not the same kind of number: R&D is a total over a full year ("FY"),
    # while cash is a balance on a date and comes from whichever filing reported
    # it most recently, usually a quarter. storing the period is what lets the app
    # say which it is showing instead of labelling both as a fiscal year.
    fiscal_period = Column(String)   # "FY", "Q1", "Q2", "Q3"
    period_end = Column(String)      # ISO date, e.g. "2026-06-30"
    fetched_at = Column(DateTime, default=_now)

    company = relationship("Company", back_populates="financials")


class Filing(Base):
    __tablename__ = "filings"

    # one row per annual report we read the narrative out of. it records what was
    # extracted as well as what was fetched, because a filing yielding no risk
    # factors is a normal outcome and has to be distinguishable from never having
    # been read at all. without that, a gap in the data looks like a fact about
    # the company.
    id = Column(Integer, primary_key=True, autoincrement=True)
    company_ticker = Column(String, ForeignKey("companies.ticker"), index=True)
    form = Column(String)            # "10-K", or "20-F" for a foreign issuer
    filed = Column(String)           # ISO date the filing was submitted
    accession = Column(String)       # EDGAR's id for it, unique per filing
    document = Column(String)        # the primary document's filename
    text_chars = Column(Integer)     # size of the whole filing once stripped to text
    # which sections were found, comma separated, empty when none were. a filing
    # can incorporate its risk factors by reference or use headings the reader
    # doesn't recognise, and this is what makes that visible rather than silent.
    sections_found = Column(String)
    # how long each section came out, so a partial extraction is detectable.
    # "found" is not enough: Pfizer's risk factors extracted as 10k characters
    # against a normal 200k, which reads as present and is not, and the only
    # signal was the length. these make that a query rather than a hunch.
    risk_factors_chars = Column(Integer)
    mdna_chars = Column(Integer)
    fetched_at = Column(DateTime, default=_now)

    company = relationship("Company", back_populates="filings")
    chunks = relationship("FilingChunk", back_populates="filing",
                          cascade="all, delete-orphan")


class FilingChunk(Base):
    __tablename__ = "filing_chunks"

    # a piece of one section, small enough that its embedding means something. a
    # biotech's risk factors run past 300,000 characters, and one vector over all
    # of that describes nothing in particular.
    id = Column(Integer, primary_key=True, autoincrement=True)
    filing_id = Column(Integer, ForeignKey("filings.id"), index=True)
    section = Column(String, index=True)   # "risk_factors" or "mdna"
    ordinal = Column(Integer)              # position within the section, from 0
    text = Column(Text)
    embedding = Column(Embedding)

    filing = relationship("Filing", back_populates="chunks")


class RegistryTrial(Base):
    __tablename__ = "registry_trials"

    # trials from the wider registry, deliberately NOT in the trials table.
    # that one holds studies led by a company in our universe, and every pipeline
    # count, phase label and signal is computed from it. Mixing a hundred thousand
    # studies run by everyone else into it would silently turn a competitor's
    # Phase 3 into part of a company's own pipeline, which is the one thing the
    # grounded numbers cannot survive.
    #
    # This table answers a different question: who else is developing for this
    # indication, and when are their readouts due.
    id = Column(Integer, primary_key=True, autoincrement=True)
    nct_id = Column(String, index=True, unique=True)
    sponsor = Column(String, index=True)
    sponsor_class = Column(String)        # INDUSTRY, NIH, OTHER, ...
    phase = Column(String, index=True)
    status = Column(String, index=True)
    conditions = Column(Text)             # what it studies, joined with "; "
    # dates carry whether they happened or are forecast. an estimated completion
    # is when a readout is expected; an actual one is when it arrived. reporting
    # the first as though it were the second would invent history.
    start_date = Column(String)
    start_date_type = Column(String)      # ACTUAL or ESTIMATED
    completion_date = Column(String)
    completion_date_type = Column(String)
    enrollment = Column(Integer)
    enrollment_type = Column(String)
    fetched_at = Column(DateTime, default=_now)
