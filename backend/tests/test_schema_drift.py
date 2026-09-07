"""
The check that says what the database is missing.

create_all creates missing tables and never missing columns, so a column added
to models.py after a database was built is absent and nothing complains until a
query names it. That is how financials.unit reached production: a dump taken
before the column, restored after it, surfacing as a 500 on whichever page
queried it first while the service reported itself healthy throughout.
"""

from sqlalchemy import Column, Integer, String, Table, text

from app.database import missing_columns
from app.models import Base


def test_a_matching_database_reports_nothing(db, monkeypatch):
    from app import database
    monkeypatch.setattr(database, "engine", db.get_bind())
    Base.metadata.create_all(db.get_bind())

    assert missing_columns() == []


def test_a_column_the_database_lacks_is_named(db, monkeypatch):
    from app import database
    engine = db.get_bind()
    monkeypatch.setattr(database, "engine", engine)
    Base.metadata.create_all(engine)
    # a column added to the models after the database was built, which is
    # exactly what a restored dump looks like against newer code
    extra = Table("financials", Base.metadata, Column("made_up_later", String),
                  extend_existing=True)
    try:
        found = missing_columns()
        assert any("financials.made_up_later" in f for f in found), found
    finally:
        extra.c.made_up_later.table = None
        extra._columns.remove(extra.c.made_up_later)


def test_a_table_the_database_lacks_is_not_reported_as_columns(db, monkeypatch):
    # create_all makes missing tables on startup, so listing all of their
    # columns as drift would be noise about something already handled
    from app import database
    engine = db.get_bind()
    monkeypatch.setattr(database, "engine", engine)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE financials"))

    assert not any(f.startswith("financials.") for f in missing_columns())
