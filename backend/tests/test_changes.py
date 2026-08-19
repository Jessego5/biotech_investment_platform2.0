"""
These are the tests for comparing two snapshots. The comparison is what turns the
archive into an answer to "what changed", so what it must not do is report change
that did not happen. It did exactly that once: a sponsor whose fetch is truncated
gets a different subset of its studies each run, and comparing them claimed 1,178
changes at Pfizer in a fortnight when seven trials had been registered. That case
is pinned first. Run them with pytest.
"""

import pytest

from app.changes import (trial_changes, financial_changes, compare, load_pair,
                         MATERIAL_CHANGE)

SPONSOR = "Alpha Therapeutics"


def study(nct, status="RECRUITING", phase=("PHASE2",), sponsor=SPONSOR):
    return {"protocolSection": {
        "identificationModule": {"nctId": nct, "briefTitle": f"Study {nct}"},
        "statusModule": {"overallStatus": status},
        "designModule": {"phases": list(phase)},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor}},
    }}


def payload(studies, total=None, truncated=False):
    return {"studies": studies, "totalCount": total if total is not None else len(studies),
            "truncated": truncated}


def figure(value, period_end, fiscal_year=2026):
    return {"value": value, "fiscal_year": fiscal_year, "fiscal_period": "Q2",
            "period_end": period_end}


# - the truncation rule, which is the bug this file exists for

def test_a_truncated_sponsor_reports_no_trial_level_change():
    # we hold a different 1,000 of several thousand each run, so every study that
    # rotates out would otherwise read as a withdrawal
    before = payload([study("NCT001"), study("NCT002")], total=6061, truncated=True)
    after = payload([study("NCT003"), study("NCT004")], total=6068, truncated=True)

    kinds = {c["kind"] for c in trial_changes(before, after, SPONSOR)}

    assert kinds == {"sponsor_total_changed"}


def test_a_truncated_sponsor_reports_the_registry_total():
    before = payload([study("NCT001")], total=6061, truncated=True)
    after = payload([study("NCT002")], total=6068, truncated=True)

    change = trial_changes(before, after, SPONSOR)[0]

    assert "6,061 -> 6,068" in change["detail"]
    # the absence of trial detail has to be explained, or it reads as nothing
    # having happened at the largest companies in the universe
    assert "not compared" in change["note"]


def test_a_truncated_sponsor_whose_total_held_still_reports_nothing():
    before = payload([study("NCT001")], total=6061, truncated=True)
    after = payload([study("NCT002")], total=6061, truncated=True)

    assert trial_changes(before, after, SPONSOR) == []


def test_truncation_on_either_side_is_enough_to_suppress():
    # a sponsor that grew past the ceiling between runs is just as uncomparable
    before = payload([study("NCT001")], total=900, truncated=False)
    after = payload([study("NCT002")], total=1200, truncated=True)

    kinds = {c["kind"] for c in trial_changes(before, after, SPONSOR)}

    assert "trial_no_longer_listed" not in kinds


# - the ordinary case, where the whole pipeline is held

def test_a_new_trial_is_reported_as_registered():
    before = payload([study("NCT001")])
    after = payload([study("NCT001"), study("NCT002")])

    changes = trial_changes(before, after, SPONSOR)

    assert [(c["kind"], c["nct_id"]) for c in changes] == [("trial_registered", "NCT002")]


def test_a_vanished_trial_is_not_called_a_withdrawal():
    # the search returning fewer results is a different claim from the sponsor
    # withdrawing a study, and only one of them is supported by the data
    before = payload([study("NCT001"), study("NCT002")])
    after = payload([study("NCT001")])

    change = trial_changes(before, after, SPONSOR)[0]

    assert change["kind"] == "trial_no_longer_listed"


def test_a_status_flip_is_reported_with_both_values():
    before = payload([study("NCT001", status="RECRUITING")])
    after = payload([study("NCT001", status="TERMINATED")])

    change = trial_changes(before, after, SPONSOR)[0]

    assert change["kind"] == "status_changed"
    assert change["detail"] == "RECRUITING -> TERMINATED"


@pytest.mark.parametrize("status, expected", [
    ("TERMINATED", True), ("SUSPENDED", True), ("WITHDRAWN", True),
    ("COMPLETED", True), ("ACTIVE_NOT_RECRUITING", False),
])
def test_only_outcomes_worth_an_alert_are_marked_notable(status, expected):
    before = payload([study("NCT001", status="RECRUITING")])
    after = payload([study("NCT001", status=status)])

    assert trial_changes(before, after, SPONSOR)[0]["notable"] is expected


def test_a_phase_advance_is_reported():
    before = payload([study("NCT001", phase=("PHASE1", "PHASE2"))])
    after = payload([study("NCT001", phase=("PHASE2", "PHASE3"))])

    change = [c for c in trial_changes(before, after, SPONSOR)
              if c["kind"] == "phase_changed"][0]

    assert change["detail"] == "PHASE1, PHASE2 -> PHASE2, PHASE3"


def test_an_unchanged_pipeline_reports_nothing():
    p = payload([study("NCT001"), study("NCT002")])

    assert trial_changes(p, p, SPONSOR) == []


def test_a_trial_led_by_another_sponsor_is_ignored():
    # the same filter ingestion applies, so the comparison sees what was stored
    before = payload([study("NCT001")])
    after = payload([study("NCT001"), study("NCT999", sponsor="Someone Else")])

    assert trial_changes(before, after, SPONSOR) == []


# - financial figures

def test_a_figure_refiled_for_the_same_period_is_not_news():
    # the same number appearing again is not a change, and reporting it would
    # bury the real ones
    before = {"cash": figure(100, "2026-03-31")}
    after = {"cash": figure(100, "2026-03-31")}

    assert financial_changes(before, after) == []


def test_a_restatement_of_the_same_period_is_still_not_reported():
    # the value moved, but the period did not, so this is a correction rather
    # than the company having done something
    before = {"cash": figure(100, "2026-03-31")}
    after = {"cash": figure(200, "2026-03-31")}

    assert financial_changes(before, after) == []


def test_a_new_period_with_a_material_move_is_reported():
    before = {"cash": figure(100_000, "2026-03-31")}
    after = {"cash": figure(50_000, "2026-06-30")}

    change = financial_changes(before, after)[0]

    assert change["metric"] == "cash"
    assert change["change"] == pytest.approx(-0.5)
    assert "2026-03-31" in change["detail"] and "2026-06-30" in change["detail"]


def test_a_move_too_small_to_matter_is_left_out():
    # below the floor it is usually rounding or a restatement
    small = 1 + (MATERIAL_CHANGE / 2)
    before = {"cash": figure(100_000, "2026-03-31")}
    after = {"cash": figure(int(100_000 * small), "2026-06-30")}

    assert financial_changes(before, after) == []


def test_a_company_that_has_not_filed_since_reports_nothing():
    # every period_end identical, so there is nothing new to compare
    before = {"cash": figure(1, "2026-03-31"), "revenue": figure(2, "2025-12-31")}

    assert financial_changes(before, before) == []


def test_a_zero_baseline_does_not_divide_by_zero():
    before = {"revenue": figure(0, "2026-03-31")}
    after = {"revenue": figure(500, "2026-06-30")}

    assert financial_changes(before, after) == []


def test_a_metric_only_present_in_one_snapshot_is_skipped():
    # a figure appearing for the first time has nothing to be compared against
    before = {}
    after = {"debt": figure(500, "2026-06-30")}

    assert financial_changes(before, after) == []


def test_an_unavailable_financials_payload_is_not_an_error():
    before = {"available": False, "reason": "IFRS filer"}
    after = {"available": False, "reason": "IFRS filer"}

    assert financial_changes(before, after) == []


# - reading the pair out of the archive

class FakeStore:
    def __init__(self, objects):
        self.objects = objects

    def get(self, key):
        return self.objects[key]


def keys(ticker, date, trials, financials):
    return {f"raw/clinicaltrials/{date}/{ticker}.json.gz": trials,
            f"raw/sec/{date}/{ticker}.json.gz": financials}


def test_a_company_missing_from_either_date_is_not_compared():
    # otherwise a company that simply was not in the earlier run would have its
    # entire pipeline reported as newly registered
    store = FakeStore(keys("AAA", "2026-08-19", payload([study("NCT001")]), {}))

    assert compare(store, "AAA", SPONSOR, "2026-08-07", "2026-08-19") is None
    assert load_pair(store, "AAA", "2026-08-07", "2026-08-19") is None


def test_compare_reports_both_kinds_of_change_together():
    objects = {}
    objects.update(keys("AAA", "2026-08-07", payload([study("NCT001", status="RECRUITING")]),
                        {"cash": figure(100_000, "2026-03-31")}))
    objects.update(keys("AAA", "2026-08-19", payload([study("NCT001", status="TERMINATED")]),
                        {"cash": figure(40_000, "2026-06-30")}))

    result = compare(FakeStore(objects), "AAA", SPONSOR, "2026-08-07", "2026-08-19")

    assert result["from"] == "2026-08-07" and result["to"] == "2026-08-19"
    assert {c["kind"] for c in result["changes"]} == {"status_changed", "figure_changed"}


# - caching, which is safe only because the archive never changes

def test_a_repeated_comparison_does_not_reread_the_archive():
    # reading a thousand compressed snapshots is the whole cost of the feature,
    # and a snapshot never changes once written
    objects = {}
    objects.update(keys("AAA", "2026-08-07", payload([study("NCT001")]), {}))
    objects.update(keys("AAA", "2026-08-19", payload([study("NCT002")]), {}))

    class CountingStore(FakeStore):
        reads = 0

        def get(self, key):
            CountingStore.reads += 1
            return super().get(key)

    store = CountingStore(objects)
    from app.changes import compare_universe
    compare_universe(store, {"AAA": SPONSOR}, "2026-08-07", "2026-08-19")
    after_first = CountingStore.reads
    compare_universe(store, {"AAA": SPONSOR}, "2026-08-07", "2026-08-19")

    assert after_first > 0
    assert CountingStore.reads == after_first


def test_a_different_date_pair_is_computed_separately():
    objects = {}
    for date in ("2026-08-07", "2026-08-19", "2026-08-20"):
        objects.update(keys("AAA", date, payload([study("NCT001")]), {}))
    store = FakeStore(objects)
    from app.changes import compare_universe

    a = compare_universe(store, {"AAA": SPONSOR}, "2026-08-07", "2026-08-19")
    b = compare_universe(store, {"AAA": SPONSOR}, "2026-08-07", "2026-08-20")

    assert a["to"] == "2026-08-19" and b["to"] == "2026-08-20"
