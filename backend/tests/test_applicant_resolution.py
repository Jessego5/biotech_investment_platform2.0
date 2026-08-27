"""
Deciding which company holds an approved product. The FDA names the entity on
the application, which is a subsidiary as often as not.
"""

import pytest

from applicant_resolution import resolve_all
from app.models import Company, Alias


def _setup(db):
    db.add_all([
        Company(ticker="JNJ", cik="0000200406", name="JOHNSON & JOHNSON", sector="x"),
        Company(ticker="ABBV", cik="0001551152", name="AbbVie Inc.", sector="x"),
    ])
    db.add_all([
        Alias(cik="0000200406", company_ticker="JNJ",
              alias="Janssen Pharmaceuticals, Inc.",
              alias_key="janssen pharmaceuticals", source="ex21"),
        Alias(cik="0001551152", company_ticker="ABBV", alias="Pharmacyclics LLC",
              alias_key="pharmacyclics", source="ex21"),
    ])
    db.commit()
    return db.query(Company).all()


def test_a_subsidiary_resolves_to_the_company_that_owns_it(db):
    # this is the whole point. "Janssen Pharmaceuticals" and "Johnson & Johnson"
    # share no words, so no spelling rule reaches across the gap
    companies = _setup(db)
    got = resolve_all(db, ["JANSSEN PHARMACEUTICALS INC", "PHARMACYCLICS LLC"],
                      companies)
    assert got["JANSSEN PHARMACEUTICALS INC"] == ("JNJ", "Exhibit 21 subsidiary")
    assert got["PHARMACYCLICS LLC"] == ("ABBV", "Exhibit 21 subsidiary")


def test_the_filing_name_is_tried_before_any_subsidiary_list(db):
    # a company holding a product under its own name must never be attributed
    # through somebody else's Exhibit 21
    companies = _setup(db)
    got = resolve_all(db, ["AbbVie Inc."], companies)
    assert got["AbbVie Inc."] == ("ABBV", "filing name")


def test_an_unknown_applicant_stays_unattributed(db):
    # most of the Orange Book belongs to private generic houses that are not in
    # the universe and should not be forced into it
    companies = _setup(db)
    assert resolve_all(db, ["KNOA PHARMA LLC"], companies) == {}


def test_a_near_match_is_not_good_enough(db):
    # an extra approved product looks exactly like a real one, so a wrong
    # attribution here is invisible in a way a wrong trial is not
    companies = _setup(db)
    assert resolve_all(db, ["AbbVie Biotherapeutics Research Ltd"], companies) == {}
