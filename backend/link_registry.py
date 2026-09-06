"""
This links the wider registry to the companies we track. registry_trials holds
112,812 industry-sponsored interventional studies and had no company column at
all, so the question it was ingested to answer, who else is developing for this
indication and when do they report, could not be joined to anything we hold
figures for. Most of the registry stays unlinked and that is the point rather
than a shortfall, since it is run by private companies, foreign parents and firms
outside the universe, and forcing those into a ticker would invent a
relationship; a null here means not a company we track, which is a different
statement from not a company. Resolution uses the same three routes the trial and
FDA joins use and no looser ones, because attributing a competitor's Phase 3 to
the wrong company is exactly the failure the strict rules exist to prevent. Run
it with python link_registry.py, or --dry-run to report what it would link.
"""

import argparse
from collections import defaultdict

from app.data_sources import identity, parent_named_in, _norm
from app.database import SessionLocal
from app.models import Alias, Company, RegistryTrial

BATCH = 500


def build_index(db):
    """Company names by leading word, and alias keys to a ticker."""
    by_first = defaultdict(list)
    for c in db.query(Company).all():
        key = _norm(c.name)
        if key:
            by_first[key.split()[0]].append(c)

    aliases = {}
    for key, ticker in db.query(Alias.alias_key, Alias.company_ticker).distinct():
        if key and ticker:
            aliases.setdefault(key, ticker)
    return by_first, aliases


def resolve(sponsor, by_first, aliases):
    """(ticker, how) for one sponsor name, or (None, None)."""
    key = _norm(sponsor)
    if not key:
        return None, None

    # 1. the company's own name
    for c in by_first.get(key.split()[0], ()):
        if identity(c.name, sponsor) == "exact":
            return c.ticker, "name"

    # 2. a subsidiary the company listed in its own Exhibit 21
    ticker = aliases.get(key)
    if ticker:
        return ticker, "exhibit 21"

    # 3. the registry naming the parent in plain text: "a subsidiary of Merck &
    #    Co., Inc.". This is the registry stating the relationship rather than us
    #    inferring one, which is why it is trusted here at all.
    named = parent_named_in(sponsor)
    if named:
        nkey = _norm(named)
        if nkey:
            for c in by_first.get(nkey.split()[0], ()):
                if identity(c.name, named) == "exact":
                    return c.ticker, "named parent"
            if aliases.get(nkey):
                return aliases[nkey], "named parent"
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        by_first, aliases = build_index(db)
        print(f"{len(aliases)} alias keys, "
              f"{sum(len(v) for v in by_first.values())} companies\n")

        sponsors = [s for (s,) in db.query(RegistryTrial.sponsor)
                    .filter(RegistryTrial.sponsor.isnot(None)).distinct()]
        print(f"{len(sponsors)} distinct sponsors in the registry")

        resolved, how_counts = {}, defaultdict(int)
        for sponsor in sponsors:
            ticker, how = resolve(sponsor, by_first, aliases)
            if ticker:
                resolved[sponsor] = ticker
                how_counts[how] += 1

        print(f"{len(resolved)} resolve to a company we track "
              f"({', '.join(f'{k}: {v}' for k, v in sorted(how_counts.items()))})")

        if args.dry_run:
            studies = (db.query(RegistryTrial)
                         .filter(RegistryTrial.sponsor.in_(list(resolved)[:0] or [""]))
                         .count())
            print("dry run: nothing written")
            return

        # written in batches keyed on the sponsor string, which is indexed
        written = 0
        items = list(resolved.items())
        for i in range(0, len(items), BATCH):
            for sponsor, ticker in items[i:i + BATCH]:
                written += (db.query(RegistryTrial)
                              .filter(RegistryTrial.sponsor == sponsor)
                              .update({"company_ticker": ticker},
                                      synchronize_session=False))
            db.commit()
            print(f"  ...{min(i + BATCH, len(items))}/{len(items)} sponsors, "
                  f"{written} studies linked")

        total = db.query(RegistryTrial).count()
        linked = db.query(RegistryTrial).filter(
            RegistryTrial.company_ticker.isnot(None)).count()
        firms = db.query(RegistryTrial.company_ticker).filter(
            RegistryTrial.company_ticker.isnot(None)).distinct().count()
        print(f"\n{linked} of {total} studies ({100 * linked / total:.1f}%) now "
              f"reach one of {firms} companies.")
        print("The rest are sponsored by companies outside the universe, which is "
              "what a null here means.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
