"""
This decides which of our companies holds an FDA-approved product. The FDA files
name the entity that holds the application, which is a subsidiary as often as
not, Janssen Pharmaceuticals rather than Johnson & Johnson and Pharmacyclics
rather than AbbVie, so matching on spelling is not a hard problem but an
impossible one when the names have nothing in common. Resolution runs in two
passes and both demand an exact identity: the company's own filing name, which
catches the plain cases, then the alias table, which is mostly Exhibit 21 to the
10-K, a company's own annual statement of the subsidiaries it owns. A near match
is deliberately never accepted, because attributing somebody else's approved
drug is worse than leaving one unattributed and the mistake would be invisible,
an extra approved product looking exactly like a real one. Imported by the
ingest and resolution scripts rather than run on its own.
"""

from app.models import Alias
from build_company_universe import identity, _norm


def build_index(db, companies):
    """
    Two lookups: company names by leading word, and alias keys to a ticker.

    Aliases are keyed on the normalised name because that is what an exact
    identity compares, and an alias claimed by two companies has already been
    dropped when the table was written.
    """
    by_first = {}
    for c in companies:
        key = _norm(c.name)
        if key:
            by_first.setdefault(key.split()[0], []).append(c)

    aliases = {}
    for a in db.query(Alias).all():
        if a.alias_key and a.company_ticker:
            aliases.setdefault(a.alias_key, a.company_ticker)
    return by_first, aliases


def resolve(applicant, by_first, aliases):
    """(ticker, how) for one applicant name, or (None, None)."""
    key = _norm(applicant)
    if not key:
        return None, None
    # the filing name first, so a company that holds a product under its own
    # name is never attributed through somebody's subsidiary list
    for c in by_first.get(key.split()[0], ()):
        if identity(c.name, applicant) == "exact":
            return c.ticker, "filing name"
    ticker = aliases.get(key)
    if ticker:
        return ticker, "Exhibit 21 subsidiary"
    return None, None


def resolve_all(db, applicants, companies):
    """applicant -> (ticker, how), for every one that resolves."""
    by_first, aliases = build_index(db, companies)
    out = {}
    for name in applicants:
        ticker, how = resolve(name, by_first, aliases)
        if ticker:
            out[name] = (ticker, how)
    return out
