"""
This script loads the wider trial registry: every industry-sponsored
interventional study, not only those run by companies in our universe. It is what
lets the app answer who else is developing for an indication, and when their
readouts are due, which the company-by-company view cannot see at all.

It writes to registry_trials and never touches trials. That table holds studies
led by a tracked company and every pipeline count and grounded signal is computed
from it, so a competitor's Phase 3 landing there would quietly become part of
somebody else's pipeline.

    python ingest_registry.py            # the whole filtered registry
    python ingest_registry.py --limit 5  # a few pages, to try it out

About 113 pages of 1,000 studies. Re-running updates what changed and adds what
is new, so an interrupted run costs only the pages it had not reached.
"""

import argparse
import time

from app.database import SessionLocal, init_db
from app.models import RegistryTrial
from app.registry import fetch_registry_page, parse_registry_study

# a pause between pages. each is several megabytes, which is a heavier ask than
# the per-sponsor queries ingestion makes.
PAUSE = 0.3


def store_page(db, studies):
    """Upsert one page. Returns (added, updated)."""
    parsed = [parse_registry_study(s) for s in studies]
    parsed = [p for p in parsed if p["nct_id"]]
    if not parsed:
        return 0, 0

    # one query for the whole page rather than one per study, since a page is a
    # thousand of them
    existing = {t.nct_id: t for t in db.query(RegistryTrial).filter(
        RegistryTrial.nct_id.in_([p["nct_id"] for p in parsed])).all()}

    added = updated = 0
    for row in parsed:
        trial = existing.get(row["nct_id"])
        if trial is None:
            db.add(RegistryTrial(**row))
            added += 1
        else:
            # a re-run should reflect what changed, which is the point of
            # running it again
            for field, value in row.items():
                setattr(trial, field, value)
            updated += 1
    return added, updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after this many pages, for a trial run")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    token, page, total_added, total_updated, reported = None, 0, 0, 0, None
    while True:
        studies, token, total = fetch_registry_page(token)
        if reported is None and total:
            reported = total
            print(f"Registry reports {total:,} industry-sponsored interventional "
                  f"studies.\n")
        added, updated = store_page(db, studies)
        db.commit()
        page += 1
        total_added += added
        total_updated += updated
        print(f"  page {page:>3}  +{added:>4} new  ~{updated:>4} updated  "
              f"({total_added + total_updated:,} seen)")

        if not token or (args.limit and page >= args.limit):
            break
        time.sleep(PAUSE)

    stored = db.query(RegistryTrial).count()
    db.close()
    print(f"\nDONE. {total_added:,} added, {total_updated:,} updated, "
          f"{stored:,} in the registry table.")
    if reported and stored < reported and not args.limit:
        print(f"Note: {reported - stored:,} fewer than the registry reports, "
              f"which is worth checking rather than assuming.")


if __name__ == "__main__":
    main()
