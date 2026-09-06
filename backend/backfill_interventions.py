"""
This recovers what each trial is testing from text we already hold. The registry
states interventions as a structured list and the ingest has always read it, but
only to fold into the blob we embed, after which the names were gone; that left
the candidate a company is developing recorded nowhere, since a programme has no
row of its own and the trials did not say what they tested except inside a
title. It is a migration rather than a re-ingest for the same reason
migrate_trial_fields.py was: re-ingesting replaces a company's trial rows and
drops their embeddings, so recovering a field already sitting in the stored
summary would cost a re-embed of every trial to learn what we can read locally.
Two things cannot be recovered and are left null rather than guessed. The
summary is capped at 2,000 characters, so a long brief summary may have had its
interventions cut off before they were stored, and the names were joined with
", " while a registry name may itself contain a comma, so a split cannot always
tell one name from two. A null here means we do not know what this trial tested,
which is a different statement from it having tested nothing. Run it with python
backfill_interventions.py, or --dry-run to report what it would do.
"""
import argparse
import re

from sqlalchemy import inspect, text

from app.database import SessionLocal, engine, init_db
from app.models import Trial

# the line _trial_text wrote: everything up to the end of that line
INTERVENTIONS = re.compile(r"^Interventions: (.+)$", re.M)


def ensure_column():
    """Add the column if this database predates it."""
    cols = {c["name"] for c in inspect(engine).get_columns("trials")}
    if "interventions" in cols:
        return False
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE trials ADD COLUMN interventions TEXT"))
    return True


def recover(summary):
    """The intervention names stored in a trial's embedded text, or None."""
    if not summary:
        return None
    found = INTERVENTIONS.search(summary)
    if not found:
        return None
    names = [n.strip() for n in found.group(1).split(",") if n.strip()]
    # the same arm listed twice is one intervention
    seen, unique = set(), []
    for n in names:
        key = n.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(n)
    return "; ".join(unique) or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    init_db()
    added = ensure_column()
    if added:
        print("added trials.interventions")

    db = SessionLocal()
    rows = db.query(Trial).filter(Trial.interventions.is_(None)).all()
    print(f"{len(rows)} trials without interventions\n")

    recovered = unrecoverable = 0
    for trial in rows:
        names = recover(trial.summary)
        if names:
            trial.interventions = names
            recovered += 1
        else:
            unrecoverable += 1

    if args.dry_run:
        db.rollback()
        print(f"dry run: would recover {recovered}, leaving {unrecoverable} null")
    else:
        db.commit()
        print(f"recovered {recovered}, left {unrecoverable} null")
    db.close()

    if unrecoverable:
        print("\nThe nulls are trials whose stored text did not carry the list — "
              "mostly ones whose summary hit the 2,000 character cap before the "
              "interventions were reached. They are filled in when the company "
              "is next ingested, which is an honest gap rather than a claim "
              "that the trial tested nothing.")


if __name__ == "__main__":
    main()
