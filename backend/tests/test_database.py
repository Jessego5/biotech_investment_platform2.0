"""
These are the tests for the database configuration. They cover the one thing that
has to be right for the same image to run locally on SQLite and in a container on
Postgres: which URL gets picked, and which driver arguments go with it. They only
exercise the plain functions, never open a connection, and so need no Postgres
driver installed to run. Run them with pytest.
"""

from app.database import DEFAULT_URL, database_url, connect_args_for


# - which database we point at

def test_local_runs_need_no_configuration(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # with nothing set it must still be the SQLite file next to the app
    assert database_url() == DEFAULT_URL
    assert DEFAULT_URL.startswith("sqlite:///")
    assert DEFAULT_URL.endswith("biotech.db")


def test_database_url_env_var_wins(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user@host/biotech")

    assert database_url() == "postgresql+psycopg://user@host/biotech"


def test_an_empty_env_var_is_treated_as_unset(monkeypatch):
    # a container that declares DATABASE_URL but leaves it blank should fall back
    # rather than build an unusable engine
    monkeypatch.setenv("DATABASE_URL", "")

    assert database_url() == DEFAULT_URL


# - driver arguments

def test_sqlite_gets_the_cross_thread_option():
    # FastAPI serves on several threads and SQLite blocks that by default
    assert connect_args_for("sqlite:///./biotech.db") == {"check_same_thread": False}


def test_in_memory_sqlite_gets_it_too():
    assert connect_args_for("sqlite:///:memory:") == {"check_same_thread": False}


def test_postgres_gets_no_sqlite_only_options():
    # check_same_thread is not a psycopg argument, so passing it would raise
    # the moment the container tried to connect
    assert connect_args_for("postgresql+psycopg://user@host/biotech") == {}
