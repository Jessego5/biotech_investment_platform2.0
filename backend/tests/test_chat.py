"""
These are the tests for turning a question into something the database can
answer. The planner is a language model, so the parts of its answer that can be
checked against the universe have to be, and the ticker is the one that matters:
a wrong ticker retrieves nothing and reads to the user as "no data on that
company" while the company's filing sits in the database. Asked eight times for
Recursion's ticker the model returned RCKT, RCRN, RECUR and RNLX, never RXRX,
and two of those are not tickers at all. Resolution happens here instead, against
the companies actually held. Run them with pytest.
"""

from app.chat import _resolve_company, _sector_labels

from conftest import add_company


def universe(db):
    add_company(db, "RXRX", "Recursion Pharmaceuticals, Inc.")
    add_company(db, "RCKT", "Rocket Pharmaceuticals, Inc.")
    add_company(db, "BNTX", "BioNTech SE")
    add_company(db, "SUPN", "Supernus Pharmaceuticals, Inc.")
    return db


# - resolving what the model was asked to copy down

def test_a_company_name_resolves_to_its_ticker(db):
    universe(db)

    assert _resolve_company("Recursion", db) == "RXRX"


def test_the_full_registered_name_resolves(db):
    universe(db)

    assert _resolve_company("Recursion Pharmaceuticals, Inc.", db) == "RXRX"


def test_a_ticker_given_directly_still_works(db):
    # the model is told not to supply one, but a user can type it
    universe(db)

    assert _resolve_company("RXRX", db) == "RXRX"
    assert _resolve_company("rxrx", db) == "RXRX"


def test_a_similar_name_does_not_collide(db):
    # Recursion and Rocket both begin with R and both are "Pharmaceuticals, Inc."
    universe(db)

    assert _resolve_company("Rocket", db) == "RCKT"
    assert _resolve_company("Recursion", db) == "RXRX"


def test_a_company_not_in_the_universe_resolves_to_nothing(db):
    # better to retrieve nothing knowingly than to retrieve the wrong company
    universe(db)

    assert _resolve_company("Blackstone Group", db) is None


def test_nothing_named_resolves_to_nothing(db):
    universe(db)

    assert _resolve_company(None, db) is None
    assert _resolve_company("", db) is None
    assert _resolve_company("   ", db) is None


def test_an_invented_ticker_does_not_resolve(db):
    # RCRN and RECUR came back from the model and are not tickers at all. The
    # point of resolving here is that they cannot become a company
    universe(db)

    assert _resolve_company("RCRN", db) is None
    assert _resolve_company("RECUR", db) is None


def test_the_sector_labels_come_from_the_data(db):
    # hardcoded in the prompt this went stale as soon as the universe widened:
    # it named three labels while the database held ten, so 124 medical-device
    # companies could not be reached by any filter question
    from app.models import Company
    for i, sector in enumerate(["Biologics", "Medical devices", "Diagnostics"]):
        db.add(Company(ticker=f"T{i}", cik=f"000000000{i}", name=f"N{i}",
                       sector=sector))
    db.commit()
    assert _sector_labels(db) == ["Biologics", "Diagnostics", "Medical devices"]


def test_no_sectors_is_not_an_error(db):
    assert _sector_labels(db) == []
