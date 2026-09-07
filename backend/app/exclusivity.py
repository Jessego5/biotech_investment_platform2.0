"""
This says how long a company's approved products stay protected, read from the
FDA Orange Book and the Purple Book. The signal is deliberately three-state
rather than a yes or no, because a boolean is wrong in both directions at once:
measured over the universe it reads false for 85% of companies, nearly all of
them wrongly, since a clinical-stage biotech has no approved product to list
patents against and Regeneron's are biologics that are not in the Orange Book at
all, while among the companies the book can speak about 90% are true, so where it
is computable it distinguishes almost nobody. The date is where the signal is,
since expiries run from this month to the mid-2040s and protected until 2027 and
protected until 2038 are not the same investment. Imported by main.py and by the
watchlist, which call protection_for with a ticker and a date.
"""

from sqlalchemy import func

from .models import (ApprovedProduct, ProductPatent, ProductExclusivity,
                     BiologicProduct)

# what the state means, in the app's own words
NO_PRODUCT = "no approved product"
NOT_LISTED = "approved, no listed protection"
PROTECTED = "protected"


def _rows(db, ticker):
    """This company's approved products, with their patents and exclusivity."""
    products = (db.query(ApprovedProduct)
                  .filter(ApprovedProduct.company_ticker == ticker).all())
    if not products:
        return [], [], []
    appl_nos = {p.appl_no for p in products}
    patents = (db.query(ProductPatent)
                 .filter(ProductPatent.appl_no.in_(appl_nos))
                 # a delisted patent is no longer asserted, so counting it would
                 # report a company as covered by something it gave up
                 .filter(ProductPatent.delisted.isnot(True)).all())
    exclusivity = (db.query(ProductExclusivity)
                     .filter(ProductExclusivity.appl_no.in_(appl_nos)).all())
    return products, patents, exclusivity


def _biologics(db, ticker):
    """This company's licensed biologics, from the Purple Book."""
    return (db.query(BiologicProduct)
              .filter(BiologicProduct.company_ticker == ticker).all())


# Where the patent and exclusivity rows came from. Not the download itself,
# which is a zip and would land in the reader's downloads rather than in front
# of their eyes, but the page that publishes it and says which month it is.
ORANGE_BOOK_PAGE = (
    "https://www.fda.gov/drugs/drug-approvals-and-databases/orange-book-data-files"
)
# the biologics half. Same shape of source: a file published on a schedule,
# with no address for the row inside it.
PURPLE_BOOK_PAGE = "https://purplebooksearch.fda.gov/downloads"


def orange_book_edition(db):
    """
    The day the Orange Book rows in here were fetched, or None if there are
    none.

    A patent expiry is only true as of an edition: the file is republished
    monthly, patents are delisted and added between one and the next, and a
    citation that names the source without naming when we took it cannot be
    checked against anything. This is the fetch date rather than the file's own
    month, because the fetch date is what we actually recorded.
    """
    fetched = db.query(func.max(ProductPatent.fetched_at)).scalar()
    return fetched.date().isoformat() if fetched else None


def orange_book_citation(db):
    """The dataset behind a patent answer, in the shape a citation takes."""
    edition = orange_book_edition(db)
    return {
        "kind": "dataset",
        "label": "FDA Orange Book",
        "detail": f"data file · fetched {edition}" if edition else "data file",
        "url": ORANGE_BOOK_PAGE,
    }


def purple_book_citation(db):
    """
    The other book, cited alongside the first wherever a protection answer
    depends on both.

    A company's protection state rests on the Orange Book and the Purple Book
    together: small molecules are listed in one, biologics licensed under a BLA
    in the other, and "no listed protection" is a claim about both being silent.
    Citing only the Orange Book would name half of what was checked and leave a
    reader unable to see that the biologics were looked at at all.
    """
    fetched = db.query(func.max(BiologicProduct.fetched_at)).scalar()
    edition = fetched.date().isoformat() if fetched else None
    return {
        "kind": "dataset",
        "label": "FDA Purple Book",
        "detail": f"data file · fetched {edition}" if edition else "data file",
        "url": PURPLE_BOOK_PAGE,
    }


def protection_for(db, ticker, as_of):
    """
    What protects this company's approved products, and until when.

    `as_of` is required rather than defaulted to today, because a backtest has
    to be able to ask the question as it stood on a past date, and a function
    that quietly reads the clock cannot be asked that.
    """
    products, patents, exclusivity = _rows(db, ticker)
    biologics = _biologics(db, ticker)

    if not products and not biologics:
        return {
            "state": NO_PRODUCT,
            "evidence": [
                "No approved small-molecule product, so there is nothing for the "
                "Orange Book to list. This is not a finding about the company's "
                "patents: a clinical-stage company holds its protection outside "
                "this source, and an approved biologic is licensed under a BLA "
                "and appears in the Purple Book instead."],
            "products": 0, "biologics": 0,
            "next_expiry": None, "last_expiry": None,
            "composition_of_matter": 0,
        }

    live_patents = [p for p in patents if p.expire_date and p.expire_date > as_of]
    live_excl = [e for e in exclusivity if e.expire_date and e.expire_date > as_of]
    # a biologic carries exclusivity dates and never a patent list, so its
    # protection is whichever of the three exclusivity columns is still running
    bio_dates = [d for b in biologics
                 for d in (b.orphan_exclusivity, b.ref_product_exclusivity,
                           b.interchangeable_exclusivity)
                 if d and d > as_of]
    dates = ([p.expire_date for p in live_patents]
             + [e.expire_date for e in live_excl] + bio_dates)

    if not dates:
        # what the silence means depends on which book the product is in. For a
        # small molecule the patent file is complete, so nothing running really
        # does mean generic entry is open. For a biologic no patent listing
        # exists anywhere public, so this is an absent source and not a finding.
        if biologics and not products:
            listed = sum(1 for b in biologics if b.patent_list_provided)
            note = (f"{len(biologics)} licensed biologic(s), and no exclusivity "
                    f"still running as of {as_of}. Biologic patents are largely "
                    f"unpublished, since the disputes run through the "
                    f"confidential BPCIA exchange, so this is a gap in the "
                    f"source rather than an absence of protection.")
            if listed:
                note += (f" FDA does record a patent list for {listed} of them, "
                         f"so a patent position exists on the record even though "
                         f"the patents themselves are not enumerated here.")
        else:
            note = (f"{len(products)} approved product(s), and no patent or "
                    f"exclusivity still running as of {as_of}. Generic entry is "
                    f"open, or the protection was never listed here.")
        return {
            "state": NOT_LISTED, "evidence": [note],
            "products": len(products), "biologics": len(biologics),
            "next_expiry": None, "last_expiry": None,
            "composition_of_matter": 0,
        }

    # the composition-of-matter claim is the one that actually forms a moat. A
    # product or method-of-use patent is narrower and easier to design around,
    # so counting all listed patents as equal overstates the protection.
    #
    # Counted as distinct patent numbers, not as rows. The file carries one row
    # per product a patent is listed against, so a single patent covering eight
    # strengths appears eight times: 22,205 rows are 7,043 patents, and AbbVie's
    # composition-of-matter count read 472 when the answer is 46.
    substance = {p.patent_no for p in live_patents if p.drug_substance}

    # likewise an application is one approved drug, while a product row is one
    # strength or presentation of it. AbbVie holds 35 approved drugs, not 264.
    applications = {p.appl_no for p in products}
    held = []
    if products:
        held.append(f"{len(applications)} approved small-molecule drug(s)")
    if biologics:
        held.append(f"{len(biologics)} licensed biologic(s)")
    notes = [f"{' and '.join(held)}; protection runs to {max(dates)}, with the "
             f"nearest expiry {min(dates)}."]
    if biologics and not products:
        listed = sum(1 for b in biologics if b.patent_list_provided)
        note = ("Protection here is regulatory exclusivity only. Biologic "
                "patents are largely unpublished, so the patent position is "
                "unknown rather than absent.")
        if listed:
            note += (f" FDA records a patent list for {listed} of these "
                     f"products, which is where a patent position would be "
                     f"confirmed if it were enumerated.")
        notes.append(note)
    if substance:
        notes.append(f"{len(substance)} composition-of-matter patent(s) still "
                     f"in force, the strongest form of claim listed here.")
    elif products:
        notes.append("No composition-of-matter patent still in force; what "
                     "remains claims the formulation or an approved use, which "
                     "is narrower.")
    if live_excl:
        codes = sorted({e.code for e in live_excl if e.code})
        notes.append(f"Regulatory exclusivity also running ({', '.join(codes)}), "
                     f"which stands independently of any patent.")

    return {
        "state": PROTECTED,
        "evidence": notes,
        "products": len(applications),
        "product_rows": len(products),
        "biologics": len(biologics),
        "next_expiry": min(dates),
        "last_expiry": max(dates),
        "composition_of_matter": len(substance),
    }


def soonest_cliffs(db, as_of, limit=10):
    """
    Companies whose approved products lose protection soonest.

    protection_for answers for one company, which cannot answer "who is closest
    to a cliff", a question the data fully supports and which was reachable
    only by asking about every company in turn. This ranks them in one query.

    Only companies with something approved appear, which is the point rather
    than a limitation: a company with nothing approved has no cliff, and putting
    it at the far end of a ranking would invent a protection it does not have.
    """
    from sqlalchemy import func
    from .models import Company

    rows = (db.query(ApprovedProduct.company_ticker,
                     Company.name,
                     func.min(ProductPatent.expire_date).label("cliff"),
                     func.max(ProductPatent.expire_date).label("reach"),
                     func.count(func.distinct(ProductPatent.patent_no)).label("patents"))
              .join(ProductPatent, ProductPatent.appl_no == ApprovedProduct.appl_no)
              .join(Company, Company.ticker == ApprovedProduct.company_ticker)
              .filter(ApprovedProduct.company_ticker.isnot(None),
                      ProductPatent.delisted.isnot(True),
                      ProductPatent.expire_date > as_of)
              .group_by(ApprovedProduct.company_ticker, Company.name)
              .order_by("cliff")
              .limit(limit).all())
    return [{"ticker": t, "name": n, "next_expiry": c, "last_expiry": r,
             "patents": p} for t, n, c, r, p in rows]
