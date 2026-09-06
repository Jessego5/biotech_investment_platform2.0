"""
These are the tests for the ingestion job's own logic, the parts that decide what
a run does rather than what it fetches. Sharding is the one that has to be exactly
right: several container tasks run this at the same time against a rate-limited
API, so the slices have to cover the whole universe and never overlap, or a
company is silently skipped or fetched twice. Run them with pytest.
"""

import pytest

from app.models import Company
from ingest import select_shard, shard_from_env, archive, write_company


def universe(*tickers):
    return [{"ticker": t, "name": f"{t} Therapeutics"} for t in tickers]


# - sharding

def test_no_sharding_returns_the_whole_universe():
    rows = universe("CCC", "AAA", "BBB")

    # a plain `python ingest.py` must behave exactly as it always did
    assert select_shard(rows, 0, None) == rows
    assert select_shard(rows, 0, 1) == rows


def test_shards_together_cover_the_whole_universe():
    rows = universe(*[f"T{i:02d}" for i in range(23)])

    covered = [r for i in range(4) for r in select_shard(rows, i, 4)]

    assert sorted(r["ticker"] for r in covered) == \
        sorted(r["ticker"] for r in rows)


def test_shards_never_overlap():
    rows = universe(*[f"T{i:02d}" for i in range(23)])

    seen = [r["ticker"] for i in range(4) for r in select_shard(rows, i, 4)]

    assert len(seen) == len(set(seen))


def test_shards_are_evenly_sized():
    rows = universe(*[f"T{i:02d}" for i in range(23)])

    sizes = [len(select_shard(rows, i, 4)) for i in range(4)]

    # 23 across 4 shards, so no shard does more than one company extra
    assert max(sizes) - min(sizes) <= 1


def test_sharding_ignores_the_order_of_companies_json():
    # two tasks read the same file, but nothing guarantees the row order is
    # stable, and a different order would move companies between shards
    forwards = select_shard(universe("AAA", "BBB", "CCC", "DDD"), 0, 2)
    backwards = select_shard(universe("DDD", "CCC", "BBB", "AAA"), 0, 2)

    assert [r["ticker"] for r in forwards] == [r["ticker"] for r in backwards]


def test_shards_are_dealt_round_robin_not_in_blocks():
    # the universe is alphabetical, so contiguous blocks would put runs of
    # similar companies together and unbalance the work
    rows = universe("AAA", "BBB", "CCC", "DDD")

    assert [r["ticker"] for r in select_shard(rows, 0, 2)] == ["AAA", "CCC"]
    assert [r["ticker"] for r in select_shard(rows, 1, 2)] == ["BBB", "DDD"]


def test_more_shards_than_companies_leaves_some_empty():
    # harmless, and the alternative is a task that fails instead of no-opping
    rows = universe("AAA", "BBB")

    assert len(select_shard(rows, 0, 5)) == 1
    assert select_shard(rows, 4, 5) == []


@pytest.mark.parametrize("index", [-1, 4, 99])
def test_a_shard_outside_the_range_is_rejected(index):
    # better to fail the task loudly than to quietly ingest nothing
    with pytest.raises(ValueError):
        select_shard(universe("AAA", "BBB"), index, 4)


# - reading the shard from the environment

def test_no_shard_env_means_the_full_universe(monkeypatch):
    monkeypatch.delenv("SHARD_COUNT", raising=False)
    monkeypatch.delenv("SHARD_INDEX", raising=False)

    assert shard_from_env() == (0, None)


def test_shard_env_is_read_as_numbers(monkeypatch):
    monkeypatch.setenv("SHARD_COUNT", "8")
    monkeypatch.setenv("SHARD_INDEX", "2")

    assert shard_from_env() == (2, 8)


def test_shard_index_defaults_to_zero(monkeypatch):
    monkeypatch.setenv("SHARD_COUNT", "4")
    monkeypatch.delenv("SHARD_INDEX", raising=False)

    assert shard_from_env() == (0, 4)


# - archiving

class FakeStore:
    def __init__(self):
        self.written = {}

    def put(self, key, payload):
        self.written[key] = payload
        return key


def test_archive_stores_both_sources_under_the_run_date():
    store = FakeStore()
    raw_trials = {"studies": [{"protocolSection": {}}]}
    financials = {"available": True, "cash": {"value": 100}}

    archive(store, "2026-08-07", {"ticker": "RXRX"}, raw_trials, financials)

    assert store.written["raw/clinicaltrials/2026-08-07/RXRX.json.gz"] == raw_trials
    assert store.written["raw/sec/2026-08-07/RXRX.json.gz"] == financials


def test_write_company_records_what_the_sponsor_really_has(db):
    raw_trials = {"studies": [], "totalCount": 6061, "truncated": True}

    write_company(db, {"ticker": "PFE", "name": "Pfizer"}, [],
                  {"available": False}, raw_trials)
    db.commit()

    company = db.get(Company, "PFE")
    assert company.trial_count_total == 6061
    assert company.trials_truncated is True


def test_write_company_stores_the_period_each_figure_covers(db):
    financials = {
        "available": True,
        "rd_expense": {"value": 100, "fiscal_year": 2025,
                       "fiscal_period": "FY", "period_end": "2025-12-31"},
        "cash": {"value": 500, "fiscal_year": 2026,
                 "fiscal_period": "Q2", "period_end": "2026-06-30"},
    }

    write_company(db, {"ticker": "AAA", "name": "Alpha"}, [], financials, {})
    db.commit()

    stored = {f.metric: f for f in db.get(Company, "AAA").financials}
    assert stored["rd_expense"].fiscal_period == "FY"
    # cash keeps its own, more recent, balance date rather than the R&D year
    assert stored["cash"].period_end == "2026-06-30"


def test_write_company_handles_a_fetch_with_no_totals(db):

    write_company(db, {"ticker": "AAA", "name": "Alpha"}, [], {"available": False})
    db.commit()

    company = db.get(Company, "AAA")
    assert company.trial_count_total is None
    assert company.trials_truncated is False


def _trial(nct, summary):
    return {"nct_id": nct, "title": "t", "phase": "PHASE2", "status": "RECRUITING",
            "lead_sponsor": "Alpha", "summary": summary}


def test_an_unchanged_trial_keeps_its_vector(db):
    # writing a company replaces its trial rows. Losing the vectors on every run
    # would leave trial search returning nothing until somebody re-embedded by
    # hand, quietly, because the search filters rows with no vector out
    write_company(db, {"ticker": "AAA", "name": "Alpha"},
                  [_trial("NCT1", "a summary")], {"available": False})
    db.commit()
    db.get(Company, "AAA").trials[0].embedding = [0.5] * 1536
    db.commit()

    write_company(db, {"ticker": "AAA", "name": "Alpha"},
                  [_trial("NCT1", "a summary")], {"available": False})
    db.commit()

    kept, = db.get(Company, "AAA").trials
    assert kept.embedding is not None
    assert list(kept.embedding)[0] == 0.5


def test_a_trial_whose_text_changed_is_embedded_again(db):
    write_company(db, {"ticker": "AAA", "name": "Alpha"},
                  [_trial("NCT1", "a summary")], {"available": False})
    db.commit()
    db.get(Company, "AAA").trials[0].embedding = [0.5] * 1536
    db.commit()

    # the summary is what was embedded, so a new summary makes the old vector
    # a description of text that is no longer there
    write_company(db, {"ticker": "AAA", "name": "Alpha"},
                  [_trial("NCT1", "a different summary")], {"available": False})
    db.commit()

    changed, = db.get(Company, "AAA").trials
    assert changed.embedding is None


def test_a_new_trial_has_no_vector_to_keep(db):
    write_company(db, {"ticker": "AAA", "name": "Alpha"},
                  [_trial("NCT1", "a summary")], {"available": False})
    db.commit()
    db.get(Company, "AAA").trials[0].embedding = [0.5] * 1536
    db.commit()

    write_company(db, {"ticker": "AAA", "name": "Alpha"},
                  [_trial("NCT1", "a summary"), _trial("NCT2", "another")],
                  {"available": False})
    db.commit()

    stored = {t.nct_id: t.embedding for t in db.get(Company, "AAA").trials}
    assert stored["NCT1"] is not None
    assert stored["NCT2"] is None


def test_archive_keeps_the_payload_untouched():
    # the snapshot is only useful if it is what the API actually said, so nothing
    # may be dropped on the way in
    store = FakeStore()
    raw_trials = {"studies": [], "totalCount": 0, "someFieldWeIgnore": "keep me"}

    archive(store, "2026-08-07", {"ticker": "RXRX"}, raw_trials, {})

    stored = store.written["raw/clinicaltrials/2026-08-07/RXRX.json.gz"]
    assert stored["someFieldWeIgnore"] == "keep me"
