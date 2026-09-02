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

from app import chat
from app.chat import (_resolve_company, _sector_labels, _run_tool, TOOLS,
                      strip_invalid_citations, count_invalid_citations)

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


def test_every_tool_the_model_is_offered_can_actually_be_run(db):
    # a tool in the schema with no branch behind it would look available to the
    # model and silently return nothing
    handled = {"greeting", "decline"}          # these end the turn instead
    for t in TOOLS:
        name = t["function"]["name"]
        if name in handled:
            continue
        text, sources = _run_tool(name, {}, db, "2026-08-27")
        assert isinstance(text, str) and isinstance(sources, list), name


def test_a_tool_that_finds_nothing_says_so_in_words(db):
    # an empty string reads to the model as though it had never asked, and it
    # then answers from somewhere else
    text, sources = _run_tool("filter_companies", {"min_cash": 10**12}, db, "2026-08-27")
    assert "No companies match" in text
    assert sources == []


def test_an_unknown_tool_returns_nothing_rather_than_guessing(db):
    assert _run_tool("drop_table", {}, db, "2026-08-27") == ("", [])


def test_a_company_that_is_not_held_is_named_as_missing(db):
    text, sources = _run_tool("company_report", {"company": "Nonexistent Bio"}, db,
                              "2026-08-27")
    assert "is in the database" in text and sources == []


def test_there_is_no_tool_that_runs_arbitrary_queries(db):
    # the line that keeps "the LLM only phrases facts" true: choosing a tool is
    # not inventing a number, but handing back raw rows to compute over would be
    names = {t["function"]["name"] for t in TOOLS}
    for banned in ("sql", "query", "run_sql", "execute", "raw_query"):
        assert banned not in names


def test_a_citation_the_model_invented_is_removed():
    # the whole point of a marker here is that it can be followed. One pointing
    # at a block that does not exist is worse than no marker: it looks like
    # provenance and leads nowhere
    assert strip_invalid_citations("Cash is $6.6B [1] and runway is n/a [4].", 2) \
        == "Cash is $6.6B [1] and runway is n/a."


def test_valid_citations_survive():
    assert strip_invalid_citations("A [1] and B [2].", 2) == "A [1] and B [2]."


def test_an_answer_with_no_evidence_keeps_no_citations():
    assert strip_invalid_citations("I don't have data on that [1].", 0) \
        == "I don't have data on that."


# - a citation has to name the document, not the archive

def test_a_filing_citation_carries_the_document_a_reader_can_open():
    # "SEC EDGAR" names the kind of source. It does not let anyone open the
    # filing and disagree with us, which is the only check that matters.
    cite = chat._filing_citation({
        "ticker": "NONOF", "fiscal_year": 2025, "form": "20-F",
        "section": "intellectual_property", "filed": "2026-02-04",
        "url": "https://www.sec.gov/Archives/edgar/data/353278/x/nvo.htm",
        "chunk_id": 293976, "accession": "0000353278-26-000012",
    })

    assert cite["label"] == "NONOF FY2025 20-F"
    assert cite["url"].startswith("https://www.sec.gov/Archives/")
    # the exact passage is fetchable, not merely attributed
    assert cite["chunk_id"] == 293976


def test_a_trial_citation_points_at_the_registry_record():
    cite = chat._trial_citation({"nct_id": "NCT05155605", "ticker": "ILMN",
                                 "phase": "NA", "status": "COMPLETED"})

    assert cite["url"] == "https://clinicaltrials.gov/study/NCT05155605"


def test_a_filing_with_no_cik_cites_without_inventing_a_url():
    # a company we hold no CIK for cannot be linked to EDGAR, and a broken link
    # is worse than none: it looks checked and fails when checked
    cite = chat._filing_citation({"ticker": "AAA", "form": "10-K", "url": None,
                                  "section": "risk_factors", "filed": "2026-01-01"})

    assert cite["url"] is None
    assert cite["label"] == "AAA 10-K"


def test_counts_invalid_citations_so_the_removal_is_not_silent():
    # the marker is stripped from the prose, but the drop is reported: a
    # citation that vanishes without trace is its own kind of failure
    answer = "Cash is $6.6B [1] and runway is n/a [4]."
    assert strip_invalid_citations(answer, 2) == "Cash is $6.6B [1] and runway is n/a."
    assert count_invalid_citations(answer, 2) == 1


def test_counts_nothing_when_every_citation_resolves():
    assert count_invalid_citations("A [1] and B [2].", 2) == 0


def test_counts_every_citation_when_there_are_no_blocks():
    assert count_invalid_citations("I don't have data on that [1].", 0) == 1
