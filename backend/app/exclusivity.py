"""
How long a company's approved products stay protected, read from the FDA Orange
Book.

The signal this produces is deliberately three-state rather than a yes/no. A
boolean was the obvious shape and it is wrong in both directions at once:
measured over the universe it reads FALSE for 85% of companies, nearly all of
them wrongly, because a clinical-stage biotech has no approved product to list
patents against and Regeneron's are biologics that are not in this book at all.
And among the companies the book can speak about, 90% are TRUE, so where it is
computable it distinguishes almost nobody.

The date is where the signal is. Expiries across the book run from this month to
the mid-2040s, and "protected until 2027" and "protected until 2038" are not the
same investment.
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
            note = (f"{len(biologics)} licensed biologic(s), and no exclusivity "
                    f"still running as of {as_of}. Biologic patents are not "
                    f"published anywhere: the disputes run through the "
                    f"confidential BPCIA exchange, so this is a gap in the "
                    f"source rather than an absence of protection.")
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
    substance = [p for p in live_patents if p.drug_substance]

    held = []
    if products:
        held.append(f"{len(products)} approved small-molecule product(s)")
    if biologics:
        held.append(f"{len(biologics)} licensed biologic(s)")
    notes = [f"{' and '.join(held)}; protection runs to {max(dates)}, with the "
             f"nearest expiry {min(dates)}."]
    if biologics and not products:
        notes.append("Protection here is regulatory exclusivity only. Biologic "
                     "patents are not published, so the patent position is "
                     "unknown rather than absent.")
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
        "products": len(products),
        "biologics": len(biologics),
        "next_expiry": min(dates),
        "last_expiry": max(dates),
        "composition_of_matter": len(substance),
    }
