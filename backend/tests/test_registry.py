"""
These are the tests for the wider trial registry, the industry-sponsored studies
run by everyone rather than only the companies we track. The rule that matters
most is that these never reach the trials table: every pipeline count and
grounded signal is computed from that one, so a competitor's Phase 3 landing
there would quietly become part of somebody else's pipeline. Run them with pytest.
"""

import pytest

from app.models import RegistryTrial, Trial
from app.registry import parse_registry_study, REGISTRY_FILTER, fetch_registry_page
from ingest_registry import store_page


def study(nct="NCT001", sponsor="Pfizer", sponsor_class="INDUSTRY",
          phases=("PHASE2",), status="COMPLETED", conditions=("Crohn's Disease",),
          start=("2012-04", "ACTUAL"), completion=("2016-07", "ACTUAL"),
          enrollment=(150, "ACTUAL")):
    section = {
        "identificationModule": {"nctId": nct},
        "statusModule": {"overallStatus": status},
        "designModule": {"phases": list(phases)},
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": sponsor, "class": sponsor_class}},
        "conditionsModule": {"conditions": list(conditions)},
    }
    if start:
        section["statusModule"]["startDateStruct"] = {"date": start[0], "type": start[1]}
    if completion:
        section["statusModule"]["primaryCompletionDateStruct"] = {
            "date": completion[0], "type": completion[1]}
    if enrollment:
        section["designModule"]["enrollmentInfo"] = {
            "count": enrollment[0], "type": enrollment[1]}
    return {"protocolSection": section}


# - parsing

def test_the_fields_a_competitive_question_needs():
    row = parse_registry_study(study())

    assert row["nct_id"] == "NCT001"
    assert row["sponsor"] == "Pfizer"
    assert row["phase"] == "PHASE2"
    assert row["conditions"] == "Crohn's Disease"
    assert row["enrollment"] == 150


def test_whether_a_date_happened_is_kept():
    # an estimated completion is when a readout is expected; an actual one is
    # when it arrived. treating the first as the second would invent history.
    row = parse_registry_study(study(completion=("2027-03", "ESTIMATED")))

    assert row["completion_date"] == "2027-03"
    assert row["completion_date_type"] == "ESTIMATED"


def test_a_missing_date_is_absent_rather_than_guessed():
    row = parse_registry_study(study(start=None, completion=None))

    assert row["start_date"] is None
    assert row["completion_date_type"] is None


def test_phases_are_joined_the_same_way_the_company_trials_do_it():
    # a phase string has to mean the same thing in both tables, or a comparison
    # between them is nonsense
    assert parse_registry_study(study(phases=("PHASE2", "PHASE3")))["phase"] == \
        "PHASE2, PHASE3"


def test_a_study_with_no_phase_reads_as_na():
    assert parse_registry_study(study(phases=()))["phase"] == "N/A"


def test_several_conditions_are_kept_together():
    row = parse_registry_study(study(conditions=("Melanoma", "NSCLC")))

    assert row["conditions"] == "Melanoma; NSCLC"


def test_the_filter_asks_for_industry_interventional_only():
    # the rest of the registry is academic and observational work: real research,
    # but nothing with a company behind it to compare against
    assert "LeadSponsorClass]INDUSTRY" in REGISTRY_FILTER
    assert "StudyType]INTERVENTIONAL" in REGISTRY_FILTER


# - storing

def test_registry_studies_never_reach_the_company_trials_table(db):
    # the rule this table exists for
    store_page(db, [study("NCT001"), study("NCT002")])
    db.commit()

    assert db.query(RegistryTrial).count() == 2
    assert db.query(Trial).count() == 0


def test_a_rerun_updates_rather_than_duplicating(db):
    store_page(db, [study("NCT001", status="RECRUITING")])
    db.commit()
    added, updated = store_page(db, [study("NCT001", status="TERMINATED")])
    db.commit()

    assert (added, updated) == (0, 1)
    assert db.query(RegistryTrial).count() == 1
    assert db.query(RegistryTrial).one().status == "TERMINATED"


def test_new_studies_are_added_alongside_existing_ones(db):
    store_page(db, [study("NCT001")])
    db.commit()
    added, updated = store_page(db, [study("NCT001"), study("NCT002")])
    db.commit()

    assert (added, updated) == (1, 1)
    assert db.query(RegistryTrial).count() == 2


def test_a_study_with_no_id_is_skipped(db):
    # nothing to key it on, and inventing one would make a duplicate next run
    broken = {"protocolSection": {"identificationModule": {}}}

    assert store_page(db, [broken]) == (0, 0)
    assert db.query(RegistryTrial).count() == 0


def test_an_empty_page_is_not_an_error(db):
    assert store_page(db, []) == (0, 0)


# - fetching

def test_a_page_returns_its_studies_and_the_next_token(monkeypatch):
    import app.registry as registry

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"studies": [study("NCT001")], "nextPageToken": "t2",
                    "totalCount": 112812}

    monkeypatch.setattr(registry, "_get_with_retry", lambda *a, **k: Resp())

    studies, token, total = fetch_registry_page()

    assert len(studies) == 1 and token == "t2" and total == 112812


def test_the_last_page_has_no_token(monkeypatch):
    import app.registry as registry

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"studies": [study("NCT001")]}

    monkeypatch.setattr(registry, "_get_with_retry", lambda *a, **k: Resp())

    assert fetch_registry_page()[1] is None


def test_a_continuation_sends_the_token(monkeypatch):
    import app.registry as registry
    seen = {}

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"studies": []}

    def fake(url, params=None, **kwargs):
        seen.update(params)
        return Resp()

    monkeypatch.setattr(registry, "_get_with_retry", fake)
    fetch_registry_page("token-2")

    assert seen["pageToken"] == "token-2"
