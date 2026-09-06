"""
This finds the trials a company runs under a name the sponsor search never asks
for. ingest.py searches ClinicalTrials.gov for one name per company, the filing
name cleaned up, and keeps the studies whose lead sponsor is that company, which
misses a whole class: Autolus Therapeutics plc runs its studies as "Autolus
Limited", and a sponsor search for "Autolus Therapeutics" returns nothing at
all, so the matching rules never get to see them and the company shows an empty
pipeline that reads as a fact about the company. We already hold the answer,
because registry_trials has 112,812 industry-sponsored studies with their
sponsor names, so the names a company actually files under can be looked up
locally rather than guessed at. This asks that table which sponsors resolve to a
company, then fetches those sponsors from the registry so the trials arrive
whole, with the title and summary the semantic search needs and registry_trials
does not carry. It uses the same matching rules as everything else and no looser
ones, since attributing a competitor's Phase 3 to the wrong company is the
failure those rules exist to prevent and a script that exists to find more
trials is where that discipline is easiest to lose. Run it with python
backfill_trials.py.
"""

import argparse
import os
import time

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from sqlalchemy import func

from app.database import SessionLocal, init_db
from app.models import Company, Trial, RegistryTrial
from app.data_sources import (fetch_trials_raw, fetch_studies_by_nct,
                              parse_trials, _leads, _norm, _traded_names)

PAUSE = 0.2


def index_by_first_word(sponsors):
    """
    Registry sponsor names grouped by their first normalised word.

    Comparing every company against all 30,000 distinct sponsor names is
    millions of calls into the matching rules and does not finish, so they are
    grouped by a word every rule needs to agree on.

    A sponsor goes in under its trading names as well as its own. That was the
    hole in the first version of this: "TheRas, Inc., d/b/a BBOT (BridgeBio
    Oncology Therapeutics)" filed under "theras", BridgeBio looked under
    "bridgebio", and the rule written to join those two never got the chance.
    An index is only as good as its claim about what it is allowed to skip.
    """
    index = {}
    for sp in sponsors:
        for name in [sp] + _traded_names(sp):
            words = _norm(name).split()
            if words:
                index.setdefault(words[0], []).append(sp)
    return index


def sponsors_for(company, index):
    """
    The registry's names for this company, other than the one already searched.

    Ordered longest first only so the output reads sensibly; every one is
    fetched.
    """
    words = _norm(company.name).split()
    if not words:
        return []
    return sorted((sp for sp in index.get(words[0], [])
                   if _leads(company.name, sp)), key=len, reverse=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", metavar="LIST",
                    help="only these companies, comma separated")
    ap.add_argument("--max-trials", type=int, default=5, metavar="N",
                    help="only companies holding N or fewer trials (default 5), "
                         "since this is for empty and near-empty pipelines")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be fetched without writing")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()

    registry_sponsors = index_by_first_word(
        s for (s,) in db.query(RegistryTrial.sponsor)
                        .filter(RegistryTrial.sponsor.isnot(None)).distinct().all())
    held = dict(db.query(Trial.company_ticker, func.count(Trial.id))
                  .group_by(Trial.company_ticker).all())

    companies = db.query(Company).order_by(Company.ticker).all()
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        companies = [c for c in companies if c.ticker in wanted]
    else:
        companies = [c for c in companies
                     if held.get(c.ticker, 0) <= args.max_trials]

    print(f"Checking {len(companies)} companies against "
          f"{sum(len(v) for v in registry_sponsors.values())} sponsor names...\n")

    added = skipped = 0
    for n, company in enumerate(companies, 1):
        names = sponsors_for(company, registry_sponsors)
        if not names:
            continue

        existing = {t.nct_id for t in db.query(Trial)
                      .filter(Trial.company_ticker == company.ticker).all()}
        found = []
        for name in names:
            if args.dry_run:
                continue
            try:
                raw = fetch_trials_raw(name)
                got = {s["protocolSection"]["identificationModule"]["nctId"]
                       for s in raw.get("studies", [])}
                # The sponsor search is a text search and can miss its own
                # sponsor entirely. We already know which studies these are, so
                # fall back to asking for them by id rather than accepting the
                # search's answer as the company's pipeline.
                wanted = {i for (i,) in db.query(RegistryTrial.nct_id)
                            .filter(RegistryTrial.sponsor == name).all()}
                if wanted - got:
                    raw = fetch_studies_by_nct(sorted(wanted - got))
            except Exception as e:
                print(f"  [{n:>3}] {company.ticker:6} {name[:34]:34} FAILED: {e}")
                continue
            # parsed against the COMPANY's name, not the sponsor's, so the same
            # rule decides this as decides every other trial
            for t in parse_trials(raw, company.name):
                if t["nct_id"] not in existing:
                    existing.add(t["nct_id"])
                    found.append(t)
            time.sleep(PAUSE)

        if args.dry_run:
            print(f"  [{n:>3}] {company.ticker:6} would search: "
                  f"{', '.join(x[:40] for x in names)}")
            continue
        if not found:
            skipped += 1
            continue

        for t in found:
            db.add(Trial(
                company_ticker=company.ticker, nct_id=t["nct_id"],
                title=t["title"], phase=t["phase"], status=t["status"],
                lead_sponsor=t["lead_sponsor"], role=t.get("role", "lead"),
                summary=t.get("summary", ""), conditions=t.get("conditions"),
                start_date=t.get("start_date"),
                start_date_type=t.get("start_date_type"),
                completion_date=t.get("completion_date"),
                completion_date_type=t.get("completion_date_type"),
                enrollment=t.get("enrollment"),
                enrollment_type=t.get("enrollment_type"),
                has_results=t.get("has_results"),
                allocation=t.get("allocation"), masking=t.get("masking"),
            ))
        db.commit()
        added += len(found)
        print(f"  [{n:>3}] {company.ticker:6} +{len(found):<4} via "
              f"{', '.join(x[:34] for x in names[:2])}")

    db.close()
    print(f"\nDONE. {added} trials added. {skipped} companies had a registry "
          f"name that resolved but returned nothing new.")


if __name__ == "__main__":
    main()
