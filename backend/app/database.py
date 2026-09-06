"""
This sets up the database engine and session. By default it is a SQLite file
called biotech.db in the backend folder, which is what you get running locally,
and setting DATABASE_URL points it somewhere else instead, which is how it runs
in a container against Postgres with no code change. The engine and session
factory live here so the API and the ingestion scripts share the same setup
either way. Import SessionLocal for a session and call init_db once at startup to
create anything missing.
"""

import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .models import Base

# put the db file right next to the app package, in backend/
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "biotech.db")
DEFAULT_URL = f"sqlite:///{DB_PATH}"


def database_url():
    """
    Where the data lives. DATABASE_URL wins when it is set (the container and
    Postgres case), otherwise fall back to the local SQLite file so running
    locally still needs no configuration at all.
    """
    # treat an empty string the same as unset, since an env var set to "" in a
    # container would otherwise produce an unusable URL
    return os.environ.get("DATABASE_URL") or DEFAULT_URL


def connect_args_for(url):
    """
    Driver arguments for a database URL. check_same_thread is a SQLite-only
    option, and passing it to any other driver is an error, so it has to be
    decided from the URL rather than hardcoded.
    """
    # FastAPI serves on several threads, and SQLite refuses a connection reused
    # across threads unless we say it's fine
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


URL = database_url()

engine = create_engine(URL, connect_args=connect_args_for(URL))

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db():
    """
    Create the tables if they don't exist yet, and on Postgres make sure the
    vector extension is there first.

    The extension has to exist before the trials table is created, because the
    embedding column's type comes from it. Doing it here rather than in a
    database image's startup script means it also happens on a managed Postgres,
    where there is no startup script to hook into.
    """
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
