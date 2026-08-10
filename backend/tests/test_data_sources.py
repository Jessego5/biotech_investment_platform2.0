"""
These are the tests for the fetch and parse layer. Every network call is faked,
so they run offline and never hit ClinicalTrials.gov or SEC and never need a user
agent or a key. The point is that a change in either API's response shape fails
here loudly, instead of quietly producing empty pipelines or stale financials that
still look plausible in the app. Run them with pytest.
"""

import pytest
import requests

from app import data_sources
from app.data_sources import (_core_name, _search_term, _trial_text,
                              summarize_pipeline, fetch_trials,
                              _latest_annual, fetch_financials)


class FakeResponse:
    """Stands in for a requests Response."""

    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


# - name normalization

@pytest.mark.parametrize("raw, expected", [
    ("FATE THERAPEUTICS INC", "fate therapeutics"),
    ("Recursion Pharmaceuticals, Inc.", "recursion pharmaceuticals"),
    ("Alpha Corp.", "alpha"),
    # several stacked suffixes all come off
    ("Beta Holdings Ltd", "beta"),
    # a suffix in the middle of the name is kept, only trailing ones are peeled
    ("Company Alpha Inc", "company alpha"),
])
def test_core_name_strips_punctuation_and_trailing_suffixes(raw, expected):
    assert _core_name(raw) == expected


def test_search_term_keeps_casing_but_drops_the_suffix():
    # ", Inc." makes the ClinicalTrials.gov sponsor search miss entirely
    assert _search_term("Fate Therapeutics, Inc.") == "Fate Therapeutics"


def test_search_term_falls_back_when_stripping_leaves_nothing():
    # a name that is nothing but a suffix must not become an empty query
    assert _search_term("Inc.") == "Inc."


# - trial text

def test_trial_text_collects_every_free_text_field():
    text = _trial_text({
        "descriptionModule": {"briefSummary": "A study of thing X."},
        "conditionsModule": {"conditions": ["Melanoma", "NSCLC"]},
        "armsInterventionsModule": {"interventions": [
            {"name": "CAR-T"}, {"name": "Placebo"}, {"type": "OTHER"},
        ]},
        "eligibilityModule": {"eligibilityCriteria": "Adults 18+."},
    })
    assert "A study of thing X." in text
    assert "Conditions: Melanoma, NSCLC" in text
    # the intervention with no name is skipped rather than adding a blank
    assert "Interventions: CAR-T, Placebo" in text
    assert "Adults 18+." in text


def test_trial_text_handles_a_study_with_no_modules():
    assert _trial_text({}) == ""


def test_trial_text_is_capped_for_cheap_embeddings():
    long_summary = "x" * 5000
    text = _trial_text({"descriptionModule": {"briefSummary": long_summary}})
    assert len(text) == 2000


# - fetch_trials

def study(nct_id, lead, phases=("PHASE1",), status="RECRUITING"):
    """Build a ClinicalTrials.gov study payload."""
    return {"protocolSection": {
        "identificationModule": {"nctId": nct_id, "briefTitle": f"Study {nct_id}"},
        "statusModule": {"overallStatus": status},
        "designModule": {"phases": list(phases)},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": lead}},
    }}


def test_fetch_trials_keeps_only_trials_the_company_actually_leads(monkeypatch):
    payload = {"studies": [
        study("NCT001", "Fate Therapeutics"),
        # a different org that the sponsor search pulled in anyway
        study("NCT002", "Memorial Sloan Kettering Cancer Center"),
    ]}
    monkeypatch.setattr(data_sources.requests, "get",
                        lambda *a, **k: FakeResponse(payload))

    trials = fetch_trials("Fate Therapeutics, Inc.")

    assert [t["nct_id"] for t in trials] == ["NCT001"]


def test_fetch_trials_matches_across_suffix_differences(monkeypatch):
    # the SEC legal name and the trial sponsor name rarely match exactly
    payload = {"studies": [study("NCT001", "Recursion Pharmaceuticals Inc.")]}
    monkeypatch.setattr(data_sources.requests, "get",
                        lambda *a, **k: FakeResponse(payload))

    trials = fetch_trials("RECURSION PHARMACEUTICALS, INC.")

    assert len(trials) == 1
    assert trials[0]["lead_sponsor"] == "Recursion Pharmaceuticals Inc."


def test_fetch_trials_flattens_the_fields_the_app_stores(monkeypatch):
    payload = {"studies": [study("NCT001", "Alpha", phases=("PHASE2", "PHASE3"))]}
    monkeypatch.setattr(data_sources.requests, "get",
                        lambda *a, **k: FakeResponse(payload))

    trial = fetch_trials("Alpha")[0]

    assert trial["title"] == "Study NCT001"
    assert trial["status"] == "RECRUITING"
    # multi-phase trials are joined, which is what the late-stage check reads
    assert trial["phase"] == "PHASE2, PHASE3"


def test_fetch_trials_reports_missing_phase_as_na(monkeypatch):
    payload = {"studies": [study("NCT001", "Alpha", phases=())]}
    monkeypatch.setattr(data_sources.requests, "get",
                        lambda *a, **k: FakeResponse(payload))

    assert fetch_trials("Alpha")[0]["phase"] == "N/A"


# - retrying transient network failures

class FlakyApi:
    """Fails at the connection level a set number of times, then succeeds."""

    def __init__(self, failures, error=None, payload=None):
        self.remaining = failures
        self.error = error or requests.exceptions.ReadTimeout("timed out")
        self.payload = payload if payload is not None else {"studies": []}
        self.calls = 0

    def __call__(self, url, params=None, **kwargs):
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise self.error
        return FakeResponse(self.payload)


def test_a_dropped_connection_is_retried(monkeypatch):
    # this is the failure that quietly cost four companies in a full run
    monkeypatch.setattr(data_sources.time, "sleep", lambda s: None)
    api = FlakyApi(failures=2)
    monkeypatch.setattr(data_sources.requests, "get", api)

    resp = data_sources._get_with_retry("https://example.test")

    assert resp.status_code == 200
    assert api.calls == 3


@pytest.mark.parametrize("error", [
    requests.exceptions.ReadTimeout("timed out"),
    requests.exceptions.ConnectionError("connection aborted"),
])
def test_both_kinds_of_network_failure_are_retried(monkeypatch, error):
    monkeypatch.setattr(data_sources.time, "sleep", lambda s: None)
    api = FlakyApi(failures=1, error=error)
    monkeypatch.setattr(data_sources.requests, "get", api)

    assert data_sources._get_with_retry("https://example.test").status_code == 200


def test_retrying_gives_up_rather_than_looping(monkeypatch):
    monkeypatch.setattr(data_sources.time, "sleep", lambda s: None)
    api = FlakyApi(failures=99)
    monkeypatch.setattr(data_sources.requests, "get", api)

    with pytest.raises(requests.exceptions.RequestException):
        data_sources._get_with_retry("https://example.test")

    assert api.calls == data_sources.RETRY_ATTEMPTS


def test_a_bad_response_is_not_retried(monkeypatch):
    # a 404 is a real answer. asking again returns the same 404, so retrying it
    # only makes a run slower.
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(url)
        return FakeResponse(status_code=404)

    monkeypatch.setattr(data_sources.requests, "get", fake_get)

    assert data_sources._get_with_retry("https://example.test").status_code == 404
    assert len(calls) == 1


def test_a_failed_page_does_not_restart_the_whole_company(monkeypatch):
    # retrying the company would re-fetch the pages that already succeeded, and a
    # sponsor needing ten requests would rarely finish
    monkeypatch.setattr(data_sources.time, "sleep", lambda s: None)
    pages = [
        {"studies": [study("NCT001", "Alpha")], "totalCount": 2,
         "nextPageToken": "t1"},
        {"studies": [study("NCT002", "Alpha")]},
    ]
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params.get("pageToken"))
        # the second page fails once before working
        if params.get("pageToken") == "t1" and calls.count("t1") == 1:
            raise requests.exceptions.ReadTimeout("timed out")
        return FakeResponse(pages[1] if params.get("pageToken") else pages[0])

    monkeypatch.setattr(data_sources.requests, "get", fake_get)

    payload = data_sources.fetch_trials_raw("Alpha")

    assert len(payload["studies"]) == 2
    # the first page was fetched once, not re-fetched after the second failed
    assert calls.count(None) == 1


# - pagination

class FakePagedApi:
    """
    Stands in for ClinicalTrials.gov's paged search. Hands back one page per call
    and records the parameters it was asked with.
    """

    def __init__(self, pages, total=None):
        self.pages = pages
        self.total = total
        self.requests = []

    def __call__(self, url, params=None, **kwargs):
        self.requests.append(dict(params or {}))
        index = len(self.requests) - 1
        payload = {"studies": self.pages[index]}
        # the API only reports the total on the first page
        if index == 0 and self.total is not None:
            payload["totalCount"] = self.total
        # every page but the last carries a token for the next one
        if index < len(self.pages) - 1:
            payload["nextPageToken"] = f"token-{index + 1}"
        return FakeResponse(payload)


def test_every_page_is_followed(monkeypatch):
    # the whole bug: one request kept the first page and dropped the rest, so any
    # sponsor with more trials than a page holds was silently truncated
    api = FakePagedApi([
        [study("NCT001", "Alpha"), study("NCT002", "Alpha")],
        [study("NCT003", "Alpha")],
    ], total=3)
    monkeypatch.setattr(data_sources.requests, "get", api)

    payload = data_sources.fetch_trials_raw("Alpha")

    assert len(payload["studies"]) == 3
    assert len(api.requests) == 2


def test_the_next_page_is_requested_with_the_previous_token(monkeypatch):
    api = FakePagedApi([[study("NCT001", "Alpha")], [study("NCT002", "Alpha")]])
    monkeypatch.setattr(data_sources.requests, "get", api)

    data_sources.fetch_trials_raw("Alpha")

    # the first request asks for no particular page, the second follows the token
    assert "pageToken" not in api.requests[0]
    assert api.requests[1]["pageToken"] == "token-1"


def test_a_single_page_makes_a_single_request(monkeypatch):
    api = FakePagedApi([[study("NCT001", "Alpha")]], total=1)
    monkeypatch.setattr(data_sources.requests, "get", api)

    payload = data_sources.fetch_trials_raw("Alpha")

    assert len(api.requests) == 1
    assert payload["truncated"] is False


def test_the_real_total_is_kept_from_the_first_page(monkeypatch):
    api = FakePagedApi([[study("NCT001", "Alpha")], [study("NCT002", "Alpha")]],
                       total=6061)
    monkeypatch.setattr(data_sources.requests, "get", api)

    payload = data_sources.fetch_trials_raw("Alpha", max_studies=2)

    # what the sponsor really has, not what we managed to fetch
    assert payload["totalCount"] == 6061


def test_fetching_stops_once_the_limit_is_reached(monkeypatch):
    # a company like Pfizer registers thousands of studies and would otherwise
    # take over an entire ingestion run
    pages = [[study(f"NCT{i:03d}", "Alpha")] for i in range(10)]
    api = FakePagedApi(pages, total=10)
    monkeypatch.setattr(data_sources.requests, "get", api)

    payload = data_sources.fetch_trials_raw("Alpha", max_studies=3)

    assert len(payload["studies"]) == 3
    assert len(api.requests) == 3


def test_the_limit_is_a_ceiling_not_a_rough_figure(monkeypatch):
    # pages arrive whole, so the last one fetched usually overshoots the limit.
    # asking for at most 250 and getting 300 makes the number meaningless.
    pages = [[study(f"NCT{i}{j}", "Alpha") for j in range(100)] for i in range(5)]
    api = FakePagedApi(pages, total=500)
    monkeypatch.setattr(data_sources.requests, "get", api)

    payload = data_sources.fetch_trials_raw("Alpha", max_studies=250)

    assert len(payload["studies"]) == 250


def test_stopping_early_is_reported_as_truncated(monkeypatch):
    pages = [[study(f"NCT{i:03d}", "Alpha")] for i in range(10)]
    api = FakePagedApi(pages, total=10)
    monkeypatch.setattr(data_sources.requests, "get", api)

    payload = data_sources.fetch_trials_raw("Alpha", max_studies=3)

    # the app can now say "3 of 10" instead of presenting 3 as the whole pipeline
    assert payload["truncated"] is True


def test_a_complete_fetch_is_not_flagged_as_truncated(monkeypatch):
    api = FakePagedApi([[study("NCT001", "Alpha"), study("NCT002", "Alpha")]],
                       total=2)
    monkeypatch.setattr(data_sources.requests, "get", api)

    assert data_sources.fetch_trials_raw("Alpha")["truncated"] is False


def test_landing_exactly_on_the_limit_is_not_truncated(monkeypatch):
    # a sponsor with exactly as many trials as we allow has been fetched whole
    api = FakePagedApi([[study("NCT001", "Alpha"), study("NCT002", "Alpha")]],
                       total=2)
    monkeypatch.setattr(data_sources.requests, "get", api)

    assert data_sources.fetch_trials_raw("Alpha", max_studies=2)["truncated"] is False


def test_a_sponsor_with_no_trials_still_returns_a_usable_payload(monkeypatch):
    api = FakePagedApi([[]], total=0)
    monkeypatch.setattr(data_sources.requests, "get", api)

    payload = data_sources.fetch_trials_raw("Alpha")

    assert payload == {"studies": [], "totalCount": 0, "truncated": False}


def test_paged_results_all_reach_the_parser(monkeypatch):
    # the point of following pages is that the extra trials actually get stored
    api = FakePagedApi([
        [study("NCT001", "Alpha")],
        [study("NCT002", "Alpha")],
        [study("NCT003", "Alpha")],
    ], total=3)
    monkeypatch.setattr(data_sources.requests, "get", api)

    trials = fetch_trials("Alpha")

    assert [t["nct_id"] for t in trials] == ["NCT001", "NCT002", "NCT003"]


def test_fetch_trials_sends_the_cleaned_sponsor_query(monkeypatch):
    seen = {}

    def fake_get(url, params=None, **kwargs):
        seen.update(params)
        return FakeResponse({"studies": []})

    monkeypatch.setattr(data_sources.requests, "get", fake_get)
    fetch_trials("Fate Therapeutics, Inc.")

    assert seen["query.spons"] == "Fate Therapeutics"


# - summarize_pipeline

def trial(phase="PHASE1", status="RECRUITING"):
    return {"phase": phase, "status": status}


def test_summarize_pipeline_counts_by_phase_and_status():
    summary = summarize_pipeline([
        trial("PHASE1"), trial("PHASE1"), trial("PHASE3", "COMPLETED"),
    ])
    assert summary["total_trials"] == 3
    assert summary["by_phase"] == {"PHASE1": 2, "PHASE3": 1}
    assert summary["by_status"] == {"RECRUITING": 2, "COMPLETED": 1}


@pytest.mark.parametrize("status", [
    "RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION",
])
def test_running_statuses_count_as_active(status):
    assert summarize_pipeline([trial(status=status)])["active_trials"] == 1


@pytest.mark.parametrize("status", [
    "COMPLETED", "TERMINATED", "WITHDRAWN", "SUSPENDED", "NOT_YET_RECRUITING",
])
def test_finished_and_not_started_statuses_are_not_active(status):
    assert summarize_pipeline([trial(status=status)])["active_trials"] == 0


def test_terminated_count_is_separate_from_inactive():
    summary = summarize_pipeline([
        trial(status="TERMINATED"), trial(status="WITHDRAWN"),
        trial(status="COMPLETED"),
    ])
    # withdrawn and completed are inactive but are not terminations
    assert summary["terminated_trials"] == 1
    assert summary["active_trials"] == 0


def test_summarize_pipeline_handles_an_empty_pipeline():
    summary = summarize_pipeline([])
    assert summary == {"total_trials": 0, "by_phase": {}, "by_status": {},
                       "active_trials": 0, "terminated_trials": 0}


# - SEC EDGAR

def facts(**tags):
    """
    Build a companyfacts payload: {tag: [entries]}. A tag can name its taxonomy
    as "dei__Thing", since a keyword argument can't contain a colon.
    """
    out = {}
    for tag, entries in tags.items():
        taxonomy, _, name = tag.rpartition("__")
        out.setdefault(taxonomy or "us-gaap", {})[name] = {"units": {"USD": entries}}
    return {"facts": out}


def entry(value, year, form="10-K", fp="FY", fy=None, filed=None):
    """
    A figure covering one calendar year, the way an expense is reported. fy
    defaults to the period's own year, but can be set separately, because in the
    real data it is the fiscal year of the FILING and often isn't the same.
    """
    return {"val": value, "fy": year if fy is None else fy, "fp": fp, "form": form,
            "start": f"{year}-01-01", "end": f"{year}-12-31",
            "filed": filed or f"{year + 1}-02-15"}


def balance(value, end, fp="Q2", form="10-Q", fy=None, filed=None):
    """
    A balance-sheet figure: a value on a date, with no period. Cash is reported
    this way, which is why it has no start.
    """
    return {"val": value, "fy": int(end[:4]) if fy is None else fy, "fp": fp,
            "form": form, "end": end, "filed": filed or end}


def test_latest_annual_picks_the_newest_year_across_all_tags():
    # the company switched tags: the old tag still has data, but it is stale.
    # returning the first tag with data would pin us to 2019 forever.
    payload = facts(OldTag=[entry(100, 2019)], NewTag=[entry(500, 2024)])

    best = _latest_annual(payload, ["OldTag", "NewTag"])

    assert best["value"] == 500
    assert best["fiscal_year"] == 2024
    assert best["tag"] == "NewTag"


def test_latest_annual_skips_tags_the_company_does_not_report():
    # a tag the company never used simply isn't in the payload, which is a fact
    # rather than the 404 a per-tag request would have returned
    payload = facts(Present=[entry(300, 2023)])

    best = _latest_annual(payload, ["Missing", "Present"])

    assert best["value"] == 300


def test_a_tag_in_another_taxonomy_is_read_from_that_taxonomy():
    # share counts are reported under dei, not us-gaap
    payload = facts(dei__EntityCommonStockSharesOutstanding=[
        balance(535_342_170, "2026-07-31")])

    best = data_sources._latest_balance(
        payload, ["dei:EntityCommonStockSharesOutstanding"])

    assert best["value"] == 535_342_170


def test_a_tag_missing_from_the_payload_yields_no_entries():
    assert data_sources._entries_for(facts(Other=[entry(1, 2025)]), "Absent") == []


def test_latest_annual_ignores_quarterly_and_non_annual_forms(monkeypatch):
    PAYLOAD = facts(Tag=[
                            entry(999, 2025, form="10-Q", fp="Q3"),
                            entry(888, 2025, form="8-K", fp="FY"),
                            entry(700, 2024),
                        ])

    best = _latest_annual(PAYLOAD, ["Tag"])

    # only the real full-year 10-K figure survives
    assert best["value"] == 700
    assert best["fiscal_year"] == 2024
    assert best["fiscal_period"] == "FY"


def test_latest_annual_accepts_the_20f_filed_by_foreign_issuers(monkeypatch):
    PAYLOAD = facts(Tag=[entry(400, 2024, form="20-F")])

    assert _latest_annual(PAYLOAD, ["Tag"])["value"] == 400


def test_latest_annual_returns_none_when_nothing_qualifies(monkeypatch):
    PAYLOAD = facts(Tag=[])

    assert _latest_annual(PAYLOAD, ["Tag"]) is None


def test_a_known_cik_skips_the_ticker_file_entirely(monkeypatch):
    # SEC's ticker file lists only currently-listed companies and changes over
    # time, so a company that was in it when the universe was sourced can drop
    # out later. companies.json records the CIK precisely so that a company we
    # have good filings for doesn't start reading as "not found in EDGAR".
    monkeypatch.setattr(data_sources, "fetch_company_facts", lambda cik: {})
    monkeypatch.setattr(data_sources, "_load_ticker_map",
                        lambda: {})   # ticker no longer listed anywhere
    monkeypatch.setattr(data_sources, "_latest_annual", lambda facts, tags:
                        {"value": 1, "fiscal_year": 2025, "fiscal_period": "FY",
                         "period_end": "2025-12-31", "tag": tags[0]})
    monkeypatch.setattr(data_sources, "_latest_balance", lambda facts, tags: None)

    result = fetch_financials("CPRX", "0001369568")

    assert result["available"] is True
    assert result["cik"] == "0001369568"


def test_the_ticker_file_is_only_a_fallback(monkeypatch):
    # when no CIK is known, resolving from the ticker is still the right move
    monkeypatch.setattr(data_sources, "fetch_company_facts", lambda cik: {})
    monkeypatch.setattr(data_sources, "_load_ticker_map",
                        lambda: {"RXRX": "0001601830"})
    monkeypatch.setattr(data_sources, "_latest_annual", lambda facts, tags: None)
    monkeypatch.setattr(data_sources, "_latest_balance", lambda facts, tags: None)

    assert fetch_financials("RXRX")["cik"] == "0001601830"


def test_fetch_financials_for_a_delisted_ticker_says_why(monkeypatch):
    # an acquired company drops out of EDGAR's ticker file
    monkeypatch.setattr(data_sources, "fetch_company_facts", lambda cik: {})
    monkeypatch.setattr(data_sources, "_load_ticker_map", lambda: {})

    result = fetch_financials("VERV")

    assert result["available"] is False
    assert "not found in EDGAR" in result["reason"]


def test_fetch_financials_explains_an_ifrs_filer(monkeypatch):
    monkeypatch.setattr(data_sources, "fetch_company_facts", lambda cik: {})
    monkeypatch.setattr(data_sources, "_load_ticker_map",
                        lambda: {"BNTX": "0001776985"})
    # a 20-F filer reporting under ifrs-full has no us-gaap figures at all, so
    # both lookups have to come back empty
    monkeypatch.setattr(data_sources, "_latest_annual", lambda facts, tags: None)
    monkeypatch.setattr(data_sources, "_latest_balance", lambda facts, tags: None)

    result = fetch_financials("BNTX")

    assert result["available"] is False
    assert result["cik"] == "0001776985"
    assert "IFRS" in result["reason"]


def test_fetch_financials_returns_both_metrics_keyed_by_cik(monkeypatch):
    monkeypatch.setattr(data_sources, "fetch_company_facts", lambda cik: {})
    monkeypatch.setattr(data_sources, "_load_ticker_map",
                        lambda: {"FATE": "0001434316"})
    monkeypatch.setattr(data_sources, "_latest_annual", lambda facts, tags:
                        {"value": 100, "fiscal_year": 2024, "fiscal_period": "FY",
                         "period_end": "2024-12-31", "tag": tags[0]})
    monkeypatch.setattr(data_sources, "_latest_balance", lambda facts, tags:
                        {"value": 250, "fiscal_year": 2026, "fiscal_period": "Q2",
                         "period_end": "2026-06-30", "tag": tags[0]})

    result = fetch_financials("fate")   # lookup must be case-insensitive

    assert result["available"] is True
    assert result["cik"] == "0001434316"
    assert result["rd_expense"]["value"] == 100
    assert result["cash"]["value"] == 250


def test_rd_comes_from_the_year_and_cash_from_the_latest_balance(monkeypatch):
    # the two metrics are looked up differently on purpose: an expense only means
    # something over a full year, a balance only means something at its newest date
    monkeypatch.setattr(data_sources, "fetch_company_facts", lambda cik: {})
    monkeypatch.setattr(data_sources, "fetch_company_facts", lambda cik: {})
    monkeypatch.setattr(data_sources, "_load_ticker_map", lambda: {"AAA": "1"})
    asked = {}
    monkeypatch.setattr(data_sources, "_latest_annual", lambda facts, tags:
                        asked.setdefault("annual", tags) and None or
                        {"value": 1, "fiscal_year": 2025, "fiscal_period": "FY",
                         "period_end": "2025-12-31", "tag": tags[0]})
    monkeypatch.setattr(data_sources, "_latest_balance", lambda facts, tags:
                        asked.setdefault("balance", tags) and None or
                        {"value": 2, "fiscal_year": 2026, "fiscal_period": "Q2",
                         "period_end": "2026-06-30", "tag": tags[0]})

    result = fetch_financials("AAA")

    assert asked["annual"] == data_sources.RD_TAGS
    assert asked["balance"] == data_sources.CASH_TAGS
    assert result["rd_expense"]["fiscal_period"] == "FY"
    assert result["cash"]["fiscal_period"] == "Q2"


def test_fetch_financials_is_available_when_only_one_metric_resolves(monkeypatch):
    monkeypatch.setattr(data_sources, "fetch_company_facts", lambda cik: {})
    monkeypatch.setattr(data_sources, "fetch_company_facts", lambda cik: {})
    monkeypatch.setattr(data_sources, "_load_ticker_map", lambda: {"AAA": "1"})
    # R&D resolves, cash does not
    monkeypatch.setattr(data_sources, "_latest_annual", lambda facts, tags:
                        {"value": 50, "fiscal_year": 2024, "fiscal_period": "FY",
                         "period_end": "2024-12-31", "tag": tags[0]})
    monkeypatch.setattr(data_sources, "_latest_balance", lambda facts, tags: None)

    result = fetch_financials("AAA")

    assert result["available"] is True
    assert result["rd_expense"]["value"] == 50
    assert result["cash"] is None


# - the filing year is not the period's year

def test_the_newest_period_wins_not_the_newest_filing_label(monkeypatch):
    # the bug this guards: one 10-K restates several years of comparatives, and
    # every one of them carries the FILING's fiscal year. selecting on that field
    # picked whichever comparative came first, so Recursion's R&D read $241m
    # (its 2023 figure) when the real 2025 number was $475m, and understating the
    # burn overstates runway.
    PAYLOAD = facts(Tag=[
                            entry(241_226_000, 2023, fy=2025),
                            entry(314_421_000, 2024, fy=2025),
                            entry(475_271_000, 2025, fy=2025),
                        ])

    best = _latest_annual(PAYLOAD, ["Tag"])

    assert best["value"] == 475_271_000
    # and the year reported is the period's own, not the filing's
    assert best["fiscal_year"] == 2025


def test_a_restatement_of_the_same_period_uses_the_newest_filing(monkeypatch):
    PAYLOAD = facts(Tag=[
                            entry(100, 2025, filed="2026-02-15"),
                            entry(120, 2025, filed="2026-08-01"),
                        ])

    assert _latest_annual(PAYLOAD, ["Tag"])["value"] == 120


def test_a_partial_period_in_an_annual_filing_is_ignored(monkeypatch):
    # a 10-K also carries shorter periods, and a few months of spending compared
    # against cash on hand would overstate runway several times over
    part_year = {"val": 90, "fy": 2026, "fp": "FY", "form": "10-K",
                 "start": "2026-01-01", "end": "2026-03-31", "filed": "2026-05-01"}
    PAYLOAD = facts(Tag=[part_year, entry(400, 2025)])

    best = _latest_annual(PAYLOAD, ["Tag"])

    assert best["value"] == 400
    assert best["fiscal_year"] == 2025


def test_a_fifty_three_week_year_still_counts_as_annual(monkeypatch):
    # fiscal years aren't exactly 365 days, so the check is a window
    long_year = {"val": 500, "fy": 2025, "fp": "FY", "form": "10-K",
                 "start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-15"}
    PAYLOAD = facts(Tag=[long_year])

    assert _latest_annual(PAYLOAD, ["Tag"])["value"] == 500


def test_an_entry_with_no_period_is_skipped(monkeypatch):
    # a balance has no start date and is not a year's spending
    PAYLOAD = facts(Tag=[balance(999, "2026-06-30", fp="FY",
                                                      form="10-K")])

    assert _latest_annual(PAYLOAD, ["Tag"]) is None


# - balances

def test_latest_balance_takes_the_newest_date_including_quarters(monkeypatch):
    # the whole point: a biotech spends its cash down every quarter, so the last
    # 10-K figure is badly stale by the time anyone reads it
    PAYLOAD = facts(Tag=[
                            balance(743_294_000, "2025-12-31", fp="FY", form="10-K"),
                            balance(654_473_000, "2026-03-31", fp="Q1"),
                            balance(545_683_000, "2026-06-30", fp="Q2"),
                        ])

    best = data_sources._latest_balance(PAYLOAD, ["Tag"])

    assert best["value"] == 545_683_000
    assert best["period_end"] == "2026-06-30"
    assert best["fiscal_period"] == "Q2"


def test_latest_balance_ignores_period_totals(monkeypatch):
    # an expense entry covers a period and is not a balance
    PAYLOAD = facts(Tag=[
                            entry(999_000, 2026),
                            balance(100_000, "2026-03-31", fp="Q1"),
                        ])

    assert data_sources._latest_balance(PAYLOAD, ["Tag"])["value"] == 100_000


def test_latest_balance_prefers_the_newest_filing_for_one_date(monkeypatch):
    # the same balance date is reported again as a comparative in later filings
    PAYLOAD = facts(Tag=[
                            balance(100, "2026-03-31", filed="2026-05-01"),
                            balance(105, "2026-03-31", filed="2026-08-01"),
                        ])

    assert data_sources._latest_balance(PAYLOAD, ["Tag"])["value"] == 105


def test_latest_balance_searches_every_tag():
    payload = facts(OldTag=[balance(100, "2025-12-31")],
                    NewTag=[balance(200, "2026-06-30")])

    best = data_sources._latest_balance(payload, ["OldTag", "NewTag"])

    assert best["value"] == 200
    assert best["tag"] == "NewTag"


def test_latest_balance_skips_tags_the_company_does_not_report():
    payload = facts(Present=[balance(300, "2026-06-30")])

    assert data_sources._latest_balance(
        payload, ["Missing", "Present"])["value"] == 300


def test_latest_balance_returns_none_when_nothing_qualifies(monkeypatch):
    PAYLOAD = facts(Tag=[])

    assert data_sources._latest_balance(PAYLOAD, ["Tag"]) is None


def test_latest_balance_does_not_leak_its_sort_key(monkeypatch):
    PAYLOAD = facts(Tag=[balance(100, "2026-06-30")])

    assert "_key" not in data_sources._latest_balance(PAYLOAD, ["Tag"])
