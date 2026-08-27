"""
How long an approved product stays protected, and — more importantly — what the
absence of a row is allowed to mean.
"""

import pytest

from app.exclusivity import protection_for, NO_PRODUCT, NOT_LISTED, PROTECTED
from app.models import (Company, ApprovedProduct, ProductPatent,
                        ProductExclusivity)

TODAY = "2026-08-27"


def _company(db, ticker="TST"):
    db.add(Company(ticker=ticker, cik="0000000001", name="Test Pharma", sector="x"))
    db.commit()
    return ticker


def _product(db, ticker, appl_no="020610"):
    db.add(ApprovedProduct(appl_no=appl_no, product_no="001", appl_type="N",
                           ingredient="TESTOLOL", trade_name="Testol",
                           applicant="TEST PHARMA INC", approval_date="2015-01-01",
                           company_ticker=ticker))
    db.commit()
    return appl_no


def test_no_approved_product_is_not_a_finding_about_patents(db):
    # the whole reason this is not a boolean. 85% of the universe has no approved
    # small molecule, and a FALSE there reads as "no moat" for companies like
    # Regeneron that hold thousands of patents on biologics
    ticker = _company(db)
    result = protection_for(db, ticker, TODAY)
    assert result["state"] == NO_PRODUCT
    assert result["next_expiry"] is None
    said = " ".join(result["evidence"]).lower()
    assert "not a finding about the company's patents" in said
    assert "purple book" in said


def test_an_approved_product_reports_its_cliff_and_its_reach(db):
    ticker = _company(db)
    appl = _product(db, ticker)
    db.add_all([
        ProductPatent(appl_no=appl, product_no="001", patent_no="7625884",
                      expire_date="2029-08-24", drug_substance=True),
        ProductPatent(appl_no=appl, product_no="001", patent_no="8000000",
                      expire_date="2038-01-01", drug_substance=False,
                      drug_product=True),
    ])
    db.commit()
    r = protection_for(db, ticker, TODAY)
    assert r["state"] == PROTECTED
    # the nearest expiry is the cliff, the furthest is how long anything runs
    assert r["next_expiry"] == "2029-08-24"
    assert r["last_expiry"] == "2038-01-01"
    assert r["composition_of_matter"] == 1


def test_an_expired_patent_does_not_protect_anything(db):
    ticker = _company(db)
    appl = _product(db, ticker)
    db.add(ProductPatent(appl_no=appl, product_no="001", patent_no="1",
                         expire_date="2020-01-01", drug_substance=True))
    db.commit()
    r = protection_for(db, ticker, TODAY)
    assert r["state"] == NOT_LISTED
    assert "Generic entry is open" in " ".join(r["evidence"])


def test_a_delisted_patent_is_not_protection(db):
    # a delisted patent is no longer asserted. Counting it would report a company
    # as covered by something it gave up
    ticker = _company(db)
    appl = _product(db, ticker)
    db.add(ProductPatent(appl_no=appl, product_no="001", patent_no="1",
                         expire_date="2040-01-01", drug_substance=True,
                         delisted=True))
    db.commit()
    assert protection_for(db, ticker, TODAY)["state"] == NOT_LISTED


def test_exclusivity_protects_without_any_patent(db):
    # orphan exclusivity is seven years of complete market protection and runs
    # independently of a patent, so a drug with no live patent can still be shut
    ticker = _company(db)
    appl = _product(db, ticker)
    db.add(ProductExclusivity(appl_no=appl, product_no="001", code="ODE",
                              expire_date="2031-05-01"))
    db.commit()
    r = protection_for(db, ticker, TODAY)
    assert r["state"] == PROTECTED
    assert r["next_expiry"] == "2031-05-01"
    assert "ODE" in " ".join(r["evidence"])


def test_a_narrow_claim_is_not_reported_as_a_moat(db):
    # a formulation or method-of-use patent is easier to design around than a
    # composition-of-matter claim, so they must not be counted as equals
    ticker = _company(db)
    appl = _product(db, ticker)
    db.add(ProductPatent(appl_no=appl, product_no="001", patent_no="1",
                         expire_date="2035-01-01", drug_substance=False,
                         drug_product=True, use_code="U-141"))
    db.commit()
    r = protection_for(db, ticker, TODAY)
    assert r["composition_of_matter"] == 0
    assert "No composition-of-matter patent" in " ".join(r["evidence"])


def test_the_question_can_be_asked_of_a_past_date(db):
    # a backtest has to ask what protection looked like then, so this must not
    # read the clock for itself
    ticker = _company(db)
    appl = _product(db, ticker)
    db.add(ProductPatent(appl_no=appl, product_no="001", patent_no="1",
                         expire_date="2024-01-01", drug_substance=True))
    db.commit()
    assert protection_for(db, ticker, "2020-01-01")["state"] == PROTECTED
    assert protection_for(db, ticker, TODAY)["state"] == NOT_LISTED
