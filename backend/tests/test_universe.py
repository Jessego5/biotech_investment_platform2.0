"""
The universe's edge. It used to be drawn by a list of SIC codes; it is now drawn
by whether a filer leads trials and files financials, which puts the whole weight
on the name match being right.
"""

import pytest

import build_company_universe as universe


@pytest.fixture(autouse=True)
def no_registry(monkeypatch):
    """Most of these test the rule, not the database behind it."""
    monkeypatch.setattr(universe, "_registry_index", ({}, {}))


@pytest.mark.parametrize("filing, candidate, expected", [
    # the same company, spelled the way each source spells it
    ("RxSight, Inc.", "RxSight, Inc.", "exact"),
    ("CODEXIS, INC.", "Codexis Inc.", "exact"),
    ("Genmab A/S", "Genmab A/S", "exact"),
    # the registry adds a descriptor to a name we hold
    ("ALCON INC", "Alcon Research", "near"),
    ("Moderna, Inc.", "ModernaTX, Inc.", None),
    # a prefix of characters is not identity. Merckle is a different company,
    # and Merck KGaA of Darmstadt is a different one again on another continent
    ("MERCK & CO INC", "Merckle GmbH", None),
    ("MERCK & CO INC", "Merck Healthcare KGaA, Darmstadt, Germany", None),
    # two words apart is too far: one of Pfizer's sponsor names is a sentence
    ("PFIZER INC", "Pfizer's Upjohn has merged with Mylan to form Viatris Inc.", None),
    # a short name collides with anything
    ("GE", "General Electric Research", None),
])
def test_identity_is_word_by_word_and_at_most_one_word_apart(filing, candidate, expected):
    assert universe.identity(filing, candidate) == expected


def test_a_first_word_substring_is_not_a_match():
    # the rule this replaced matched the first word as a substring of the lead
    # sponsor, and over eight thousand filers that admitted 5.7% of a random
    # sample: Tesla, Boeing, Shell, Vale, Rocky Mountain Chocolate Factory
    for filing, lead in [("Tesla, Inc.", "Tesla Medical s.r.o."),
                         ("BOEING CO", "Boehringer Ingelheim"),
                         ("Shell plc", "Shellpoint Research"),
                         ("DANA Inc", "Danaher Corporation")]:
        assert universe.identity(filing, lead) is None, filing


def _row(monkeypatch, filing_name, sponsor, how, sic, financials=True):
    monkeypatch.setattr(universe, "registry_identity", lambda n: (sponsor, how))
    monkeypatch.setattr(universe, "fetch_sic", lambda c: (sic, "described"))
    monkeypatch.setattr(universe, "has_financials", lambda c: financials)
    return universe.check_company("0000000001",
                                  {"ticker": "TST", "name": filing_name})


def test_a_near_match_needs_a_medical_sic_behind_it(monkeypatch):
    # "Asana, Inc." to "Asana BioSciences" is the same shape as "Alcon Inc" to
    # "Alcon Research", and the trials cannot separate them: Asana BioSciences
    # runs phase-labelled studies too. The filing code is what separates them.
    assert _row(monkeypatch, "Asana, Inc.", "Asana BioSciences", "near", "7372") is None
    kept = _row(monkeypatch, "ALCON INC", "Alcon Research", "near", "3851")
    assert kept is not None
    assert kept["sector"] == "Medical devices"
    assert "SIC 3851" in kept["included_because"]


def test_an_exact_match_stands_without_a_medical_sic(monkeypatch):
    # an ADR gets a generic filing code whatever the company does, which is why
    # Shionogi and CSL file under "American Depositary Receipts". Requiring a
    # medical code would throw away exactly the companies the sweep could not see
    kept = _row(monkeypatch, "SHIONOGI & CO LTD", "Shionogi & Co., Ltd.", "exact", "6770")
    assert kept is not None
    assert kept["included_because"].startswith("exact")


def test_no_trials_means_no_row(monkeypatch):
    monkeypatch.setattr(universe, "registry_identity", lambda n: None)
    monkeypatch.setattr(universe, "api_identity", lambda n: None)
    assert universe.check_company("1", {"ticker": "X", "name": "Widget Corp"}) is None


def test_no_financials_means_no_row(monkeypatch):
    assert _row(monkeypatch, "ALCON INC", "Alcon Research", "exact", "3851",
                financials=False) is None


def test_a_company_whose_trials_are_incidental_is_named_and_dropped(monkeypatch):
    assert _row(monkeypatch, "Accenture plc", "Accenture", "exact", "8731") is None


def test_the_api_is_only_asked_when_the_registry_is_silent(monkeypatch):
    asked = []
    monkeypatch.setattr(universe, "registry_identity", lambda n: ("Alcon Research", "near"))
    monkeypatch.setattr(universe, "api_identity", lambda n: asked.append(n))
    monkeypatch.setattr(universe, "fetch_sic", lambda c: ("3851", "Ophthalmic Goods"))
    monkeypatch.setattr(universe, "has_financials", lambda c: True)
    universe.check_company("1", {"ticker": "ALC", "name": "ALCON INC"})
    assert asked == []


def test_a_failed_trials_check_is_not_an_answer(monkeypatch):
    monkeypatch.setattr(universe, "registry_identity", lambda n: None)
    def boom(name):
        raise universe.TrialCheckFailed("timeout")
    monkeypatch.setattr(universe, "api_identity", boom)
    with pytest.raises(universe.TrialCheckFailed):
        universe.check_company("1", {"ticker": "X", "name": "Real Biotech Inc"})


def test_an_unknown_sic_still_gets_a_label_from_edgar(monkeypatch):
    # the sweep could only report codes it had already decided to ask for, so
    # anything outside the list came back "Other"
    kept = _row(monkeypatch, "Widget Bio Inc", "Widget Bio Inc", "exact", "1234")
    assert kept["sector"] == "described"


def test_the_state_of_incorporation_survives_the_accent_fold():
    # folding accents away flattens "/DE/" to "de" as well, which would undo the
    # earlier state-marker fix and cost Heron, Windtree and Dianthus their
    # pipelines a second time
    assert universe._norm("HERON THERAPEUTICS, INC. /DE/") == "heron therapeutics"
    assert universe._norm("Dianthus Therapeutics, Inc. /DE/") == "dianthus therapeutics"
    assert universe._norm("VERTEX PHARMACEUTICALS INC / MA") == "vertex pharmaceuticals"
    # and the accent still folds
    assert universe._norm("Daré Bioscience, Inc.") == "dare bioscience"


def test_a_recorded_alias_reaches_a_name_no_rule_can(monkeypatch):
    # "Moderna, Inc." and "ModernaTX, Inc." are one company and no spelling rule
    # says so: they differ inside the first word, and matching a prefix of
    # characters there is what turns Merck into Merckle
    monkeypatch.setattr(universe, "_registry_index",
                        ({"modernatx": ["ModernaTX, Inc."]}, {}))
    assert universe.identity("Moderna, Inc.", "ModernaTX, Inc.") is None
    assert universe.alias_identity("0001682852") == ("ModernaTX, Inc.", "exact")
    assert universe.alias_identity("0000000000") is None


def test_an_alias_is_only_consulted_after_the_rules_fail(monkeypatch):
    asked = []
    monkeypatch.setattr(universe, "registry_identity", lambda n: ("Alcon Research", "near"))
    monkeypatch.setattr(universe, "alias_identity", lambda c: asked.append(c))
    monkeypatch.setattr(universe, "fetch_sic", lambda c: ("3851", "Ophthalmic Goods"))
    monkeypatch.setattr(universe, "has_financials", lambda c: True)
    universe.check_company("1", {"ticker": "ALC", "name": "ALCON INC"})
    assert asked == []
