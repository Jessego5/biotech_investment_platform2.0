"""
These are the tests for the embedding column type, the one place the two
databases genuinely differ. On Postgres an embedding is a pgvector column the
database can search; on SQLite it is the raw float32 bytes it has always been and
the search happens in memory. What has to hold is that Python sees the same thing
either way, and that the existing SQLite data still reads back correctly, since
that is where the current 12,943 embedded trials live. The Postgres branches are
checked by calling the type's own conversion methods with a fake dialect, because
verifying them for real needs a running Postgres. Run them with pytest.
"""

import numpy as np
import pytest

from app.models import Embedding, EMBEDDING_DIM, Trial


class FakeDialect:
    """Just enough of a dialect for the type's branching, which keys off name."""

    def __init__(self, name):
        self.name = name


SQLITE = FakeDialect("sqlite")
POSTGRES = FakeDialect("postgresql")


def vector(n=EMBEDDING_DIM):
    # a recognisable ramp rather than random, so a mangled round trip is obvious
    return np.linspace(-1.0, 1.0, n, dtype=np.float32)


# - what Python sees is the same on both

def test_sqlite_round_trip_returns_the_same_numbers():
    v = vector()
    column = Embedding()

    stored = column.process_bind_param(v, SQLITE)
    back = column.process_result_value(stored, SQLITE)

    assert isinstance(stored, bytes)
    assert np.array_equal(back, v)


def test_postgres_round_trip_returns_the_same_numbers():
    v = vector()
    column = Embedding()

    stored = column.process_bind_param(v, POSTGRES)
    back = column.process_result_value(stored, POSTGRES)

    # pgvector takes the numbers themselves rather than an encoding
    assert isinstance(stored, list)
    assert np.allclose(back, v)


def test_both_dialects_read_back_the_same_dtype():
    # the search code stacks these into one matrix, so a differing dtype between
    # databases would only show up as a subtly wrong result rather than an error
    column = Embedding()
    v = vector()

    from_sqlite = column.process_result_value(
        column.process_bind_param(v, SQLITE), SQLITE)
    from_postgres = column.process_result_value(
        column.process_bind_param(v, POSTGRES), POSTGRES)

    assert from_sqlite.dtype == from_postgres.dtype == np.float32


@pytest.mark.parametrize("dialect", [SQLITE, POSTGRES])
def test_no_embedding_stays_none(dialect):
    # a trial that has not been embedded yet, which embed_trials.py looks for
    column = Embedding()

    assert column.process_bind_param(None, dialect) is None
    assert column.process_result_value(None, dialect) is None


@pytest.mark.parametrize("dialect", [SQLITE, POSTGRES])
def test_a_plain_list_is_accepted(dialect):
    # OpenAI returns a list of floats, so the type should not require an array
    column = Embedding()

    stored = column.process_bind_param([0.5] * EMBEDDING_DIM, dialect)
    back = column.process_result_value(stored, dialect)

    assert len(back) == EMBEDDING_DIM
    assert np.allclose(back, 0.5)


# - the column each database actually gets

def test_postgres_gets_a_real_vector_column():
    # a real dialect here, not the stub above: picking the column type goes
    # through the dialect itself rather than just reading its name
    from pgvector.sqlalchemy import Vector
    from sqlalchemy.dialects import postgresql

    impl = Embedding().load_dialect_impl(postgresql.dialect())

    assert isinstance(impl, Vector)
    assert impl.dim == EMBEDDING_DIM


def test_sqlite_falls_back_to_bytes():
    from sqlalchemy import LargeBinary
    from sqlalchemy.dialects import sqlite

    impl = Embedding().load_dialect_impl(sqlite.dialect())

    assert isinstance(impl, LargeBinary)


def test_the_dimension_matches_the_model_that_produces_it():
    # text-embedding-3-small returns 1536 numbers; Postgres wants the width in
    # the column type, so a mismatch here is rejected at insert time
    from embed_trials import EMBED_MODEL

    assert EMBED_MODEL == "text-embedding-3-small"
    assert EMBEDDING_DIM == 1536


# - storing and reading through the ORM, on the database the tests run against

def test_an_embedding_survives_a_real_write_and_read(db):
    from app.models import Company
    company = Company(ticker="AAA", name="Alpha")
    v = vector()
    company.trials.append(Trial(nct_id="NCT001", title="t", summary="text",
                                embedding=v))
    db.add(company)
    db.commit()

    stored = db.query(Trial).filter(Trial.embedding.isnot(None)).one()

    assert np.array_equal(stored.embedding, v)


def test_trials_without_an_embedding_are_filterable(db):
    # this is the query embed_trials.py uses to resume, so it has to keep working
    from app.models import Company
    company = Company(ticker="AAA", name="Alpha")
    company.trials.append(Trial(nct_id="NCT001", summary="a", embedding=vector()))
    company.trials.append(Trial(nct_id="NCT002", summary="b"))
    db.add(company)
    db.commit()

    pending = db.query(Trial).filter(Trial.embedding.is_(None)).all()

    assert [t.nct_id for t in pending] == ["NCT002"]
