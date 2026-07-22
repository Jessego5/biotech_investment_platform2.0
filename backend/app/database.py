"""
This sets up the database engine and session. It is just a SQLite file called
biotech.db sitting in the backend folder. The engine and session factory live
here so the API and the ingestion script both share the same setup.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base

# put the db file right next to the app package, in backend/
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "biotech.db")

# check_same_thread is False so FastAPI, which uses multiple threads, can share the SQLite file
engine = create_engine(f"sqlite:///{DB_PATH}",
                       connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db():
    """Create the tables if they don't exist yet."""
    Base.metadata.create_all(engine)
