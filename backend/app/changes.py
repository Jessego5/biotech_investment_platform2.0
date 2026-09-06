"""
This compares two snapshots of the same company and says what changed. The
archive keeps what the APIs returned under a dated key, so the question of what
is different since last time is answerable from two stored payloads without
asking either API again. It is deliberately about changes a person would act on
and not every difference: a trial's description being reworded is a difference,
while a Phase 3 turning into TERMINATED is news. Everything reported is derived
from the two payloads and says which values it compared, so a claim can be
checked the same way every other number in this project can. Imported by main.py
for the /changes routes.
"""

from .data_sources import parse_trials
from .raw_store import get_store, raw_key, snapshot_coverage, manifest_key

# statuses worth calling out when a trial arrives in one, since they are the
# outcomes a reader is watching for rather than routine progress
NOTABLE_STATUSES = {"TERMINATED", "SUSPENDED", "WITHDRAWN", "COMPLETED"}

# how much a figure has to move before it is worth mentioning, as a fraction.
# below this it is usually a restatement or rounding rather than news.
MATERIAL_CHANGE = 0.05


def load_pair(store, ticker, earlier, later):
    """
    Read one company's trial and financial snapshots for two dates.

    Returns None when either date is missing for that company, because a company
    that was not in the earlier run has nothing to compare against and reporting
    all of its trials as new would be wrong.
    """
    try:
        return {
            "before": {
                "trials": store.get(raw_key("clinicaltrials", ticker, earlier)),
                "financials": store.get(raw_key("sec", ticker, earlier)),
            },
            "after": {
                "trials": store.get(raw_key("clinicaltrials", ticker, later)),
                "financials": store.get(raw_key("sec", ticker, later)),
            },
        }
    except (FileNotFoundError, KeyError):
        return None


def _by_nct(payload, sponsor_name):
    """{nct_id: trial} for one snapshot, parsed the same way ingestion parses it."""
    return {t["nct_id"]: t for t in parse_trials(payload, sponsor_name)
            if t.get("nct_id")}


def trial_changes(before, after, sponsor_name):
    """
    What happened to the pipeline between two snapshots.

    Registrations, disappearances, phase advances and status flips. A trial
    leaving the results is reported as "no longer listed" rather than as a
    withdrawal, because the search returning fewer results is not the same claim
    as the sponsor withdrawing a study.

    For a sponsor whose fetch was truncated, no per-trial comparison is made at
    all. We hold the first 1,000 of several thousand studies and the search does
    not return them in a stable order, so a different subset arrives each run:
    comparing them reported 1,178 changes at Pfizer in a fortnight when seven
    trials had actually been registered. Only the sponsor's own total is
    comparable there, and that is what gets reported.
    """
    if before.get("truncated") or after.get("truncated"):
        return _truncated_total_change(before, after)

    old, new = _by_nct(before, sponsor_name), _by_nct(after, sponsor_name)
    changes = []

    for nct in sorted(new.keys() - old.keys()):
        t = new[nct]
        changes.append({"kind": "trial_registered", "nct_id": nct,
                        "detail": f"{t['phase']}, {t['status']}",
                        "title": t.get("title") or ""})

    for nct in sorted(old.keys() - new.keys()):
        changes.append({"kind": "trial_no_longer_listed", "nct_id": nct,
                        "detail": f"was {old[nct]['status']}",
                        "title": old[nct].get("title") or ""})

    for nct in sorted(old.keys() & new.keys()):
        was, now = old[nct], new[nct]
        if was["status"] != now["status"]:
            changes.append({
                "kind": "status_changed", "nct_id": nct,
                "detail": f"{was['status']} -> {now['status']}",
                "title": now.get("title") or "",
                # a trial stopping is the reason anyone watches this
                "notable": now["status"] in NOTABLE_STATUSES,
            })
        if was["phase"] != now["phase"]:
            changes.append({"kind": "phase_changed", "nct_id": nct,
                            "detail": f"{was['phase']} -> {now['phase']}",
                            "title": now.get("title") or ""})
    return changes


def _truncated_total_change(before, after):
    """
    All that can honestly be said about a sponsor we only hold part of: how many
    studies the registry reports for it now against then.
    """
    was, now = before.get("totalCount"), after.get("totalCount")
    if was is None or now is None or was == now:
        return []
    return [{
        "kind": "sponsor_total_changed",
        "detail": f"{was:,} -> {now:,} registered studies",
        # say why there is no trial-level detail, rather than leaving its absence
        # to be read as nothing having happened
        "note": ("only part of this sponsor's studies are fetched, so individual "
                 "trials are not compared"),
    }]


def financial_changes(before, after):
    """
    Which reported figures moved, and by how much.

    Only compares figures reported for a different period: the same number filed
    again is not news, and a company that has not filed since the earlier
    snapshot should produce nothing at all rather than a spurious zero change.
    """
    changes = []
    for metric in sorted(set(before) | set(after)):
        was, now = before.get(metric), after.get(metric)
        if not isinstance(was, dict) or not isinstance(now, dict):
            continue
        # a new filing is what makes a figure worth comparing
        if was.get("period_end") == now.get("period_end"):
            continue
        old_value, new_value = was.get("value"), now.get("value")
        if old_value in (None, 0) or new_value is None:
            continue
        delta = (new_value - old_value) / abs(old_value)
        if abs(delta) < MATERIAL_CHANGE:
            continue
        changes.append({
            "kind": "figure_changed", "metric": metric,
            "detail": (f"{old_value:,.0f} ({was.get('period_end')}) -> "
                       f"{new_value:,.0f} ({now.get('period_end')})"),
            "change": delta,
        })
    return changes


def compare(store, ticker, sponsor_name, earlier, later):
    """
    Everything that changed for one company between two snapshot dates, or None
    when it was not present in both.
    """
    pair = load_pair(store, ticker, earlier, later)
    if pair is None:
        return None
    return {
        "ticker": ticker,
        "from": earlier,
        "to": later,
        "changes": (trial_changes(pair["before"]["trials"],
                                  pair["after"]["trials"], sponsor_name)
                    + financial_changes(pair["before"]["financials"],
                                        pair["after"]["financials"])),
    }


# how much of the newest snapshot a baseline has to cover to be worth comparing
# against. a repair run writes a date holding a handful of companies, and using
# one as the baseline reports the rest as absent rather than as unchanged.
MIN_BASELINE_COVERAGE = 0.8


def latest_pair(store):
    """
    The newest snapshot and the most recent earlier one that covers a comparable
    set of companies, oldest first. None when there is no such pair.

    Coverage matters more than recency here. The archive holds a date with eight
    companies in it, written while repairing the ones a run had lost, and taking
    simply the two newest dates would pick it and report the other 470 companies
    as missing.
    """
    coverage = snapshot_coverage()
    if len(coverage) < 2:
        return None

    # The coverage rule guarded the baseline and not the newest end, so a
    # targeted re-ingest of 48 companies became the thing everything else was
    # compared against and 739 companies came back as "not in both". A run that
    # says it was partial is not a period of time, it is a repair.
    full = [(d, c) for d, c in coverage if _was_full_run(d) is not False]
    usable = full if len(full) >= 2 else coverage

    (newest, newest_count), rest = usable[0], usable[1:]
    for date, count in rest:
        if count >= newest_count * MIN_BASELINE_COVERAGE:
            return date, newest
    return None


def _was_full_run(date):
    """
    Whether that date's run covered the whole universe: True, False, or None
    when the run left no manifest and cannot say.
    """
    try:
        return bool(get_store().get(manifest_key(date)).get("full_run"))
    except Exception:
        return None


def snapshot_provenance(earlier, later):
    """
    What produced each end of a comparison, and whether they are comparable.

    Two snapshots taken by different code are not measuring the same thing. When
    the matching rules changed, Church & Dwight appeared to register 34 trials
    in four days, one of them a benzocaine study from 2007; it had always run
    them and we had only started recognising its name. A diff that cannot say
    this will report rule changes as events.
    """
    out = {}
    for label, date in (("from", earlier), ("to", later)):
        try:
            out[label] = get_store().get(manifest_key(date))
        except Exception:
            out[label] = {"date": date, "code_version": None, "full_run": None}
    versions = {out[k].get("code_version") for k in ("from", "to")}
    out["same_code"] = (len(versions) == 1 and None not in versions)
    out["caveat"] = None if out["same_code"] else (
        "These snapshots were taken by different or unrecorded versions of the "
        "extraction code, so a difference here may be a change in what we "
        "recognise rather than a change in the world.")
    return out


# a comparison already made, keyed by the two dates and how many companies were
# asked for. safe to keep indefinitely because a snapshot never changes once
# written, so the diff between two dates is a pure function of those dates.
_comparisons = {}


def compare_universe(store, companies, earlier, later, use_cache=True):
    """
    Every company's changes between two dates, skipping the ones with nothing to
    report. companies is {ticker: sponsor_name}, since the sponsor name is what
    the trial payloads are parsed against.

    Companies present in only one of the two dates are counted separately rather
    than dropped silently: a run that missed half the universe should be visible
    as missing, not as a quiet period.

    Cached, because the work is reading a thousand compressed snapshots off disk
    rather than comparing them: about ten seconds for the universe, of which the
    comparison itself is under a fifth of a second. Repeating that per page load
    would be the whole cost of the feature for no new information.
    """
    key = (earlier, later, len(companies))
    if use_cache and key in _comparisons:
        return _comparisons[key]

    results, incomparable = [], []
    for ticker, sponsor_name in sorted(companies.items()):
        result = compare(store, ticker, sponsor_name, earlier, later)
        if result is None:
            incomparable.append(ticker)
        elif result["changes"]:
            results.append(result)
    result = {"from": earlier, "to": later, "companies": results,
              "not_in_both_snapshots": incomparable}
    if use_cache:
        _comparisons[key] = result
    return result
