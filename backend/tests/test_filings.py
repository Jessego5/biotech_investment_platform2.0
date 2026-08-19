"""
These are the tests for reading the narrative out of an annual report. A filing
has no markup saying "this is the risk factors section", so the section is found
by its heading, and every way that went wrong produced a plausible result rather
than an error: a heading that stopped matching, a citation mistaken for a
heading, and a contents line that swallowed the whole document. Each of those is
pinned below with the filing that exposed it. Run them with pytest.
"""

import pytest

from app.filings import (html_to_text, extract_sections, chunk_text, filing_url,
                         latest_annual_filing, MIN_SECTION_CHARS)


def body(marker, length=2000):
    """Filler long enough to count as a real section."""
    return f" {marker} " + "word " * (length // 5)


# - turning filing HTML into text

def test_a_word_split_by_inline_markup_stays_one_word():
    # CRISPR Therapeutics' 10-K styles the middle of a word, and replacing every
    # tag with a space turned "Risk Factors" into "Ris k Factors", which stopped
    # the heading matching and silently lost the section
    assert "Risk Factors" in html_to_text("<p>Item 1A. Ris<span>k</span> Factors</p>")


def test_block_tags_still_separate_words():
    # the other half of the same rule: without this, two paragraphs run together
    # into one nonsense word
    assert html_to_text("<p>first</p><p>second</p>") == "first second"


def test_script_and_style_contents_are_dropped():
    text = html_to_text("<style>p{color:red}</style><script>x=1</script><p>real</p>")

    assert text == "real"


def test_a_non_breaking_space_is_a_real_space():
    # it separates words, so dropping it outright would glue them together
    assert html_to_text("<p>one&nbsp;two</p>") == "one two"


def test_other_entities_do_not_introduce_spaces():
    assert html_to_text("<p>AT&amp;T</p>") == "ATT"


# - finding the sections

def make_filing(**parts):
    """A filing with a table of contents, then the sections themselves."""
    contents = ("<p>Item 1A. Risk Factors</p><p>Item 1B. Unresolved Staff "
                "Comments</p><p>Item 7. Management's Discussion</p>"
                "<p>Item 8. Financial Statements</p>")
    return contents + "".join(parts.values())


def test_the_table_of_contents_is_not_mistaken_for_the_section():
    html = make_filing(
        rf="<p>Item 1A. Risk Factors</p>" + body("REALRISKS"),
        end="<p>Item 1B. Unresolved Staff Comments</p>",
    )

    sections = extract_sections(html_to_text(html))

    assert "REALRISKS" in sections["risk_factors"]


def test_a_contents_line_cannot_swallow_the_document():
    # Recursion's contents does not list Item 1B, so its contents line paired
    # with the REAL closing heading and produced a "section" of 587k characters
    # that ran through half the filing
    html = ("<p>Item 1A. Risk Factors</p>"          # contents, no 1B alongside
            "<p>Some other part of the filing</p>" + body("FILLER") +
            "<p>Item 1A. Risk Factors</p>" + body("REALRISKS") +
            "<p>Item 1B. Unresolved Staff Comments</p>")

    sections = extract_sections(html_to_text(html))

    assert "REALRISKS" in sections["risk_factors"]
    assert "FILLER" not in sections["risk_factors"]


def test_a_cross_reference_after_the_section_is_not_the_section():
    # Fate's and AbbVie's filings end with "see Item 1A. Risk Factors" inside the
    # MD&A, and taking the last occurrence found that citation instead
    html = make_filing(
        rf="<p>Item 1A. Risk Factors</p>" + body("REALRISKS"),
        end="<p>Item 1B. Unresolved Staff Comments</p>",
        later="<p>as described under Item 1A. Risk Factors above</p>",
    )

    sections = extract_sections(html_to_text(html))

    assert "REALRISKS" in sections["risk_factors"]


def test_a_missing_closing_heading_drops_the_section_rather_than_guessing():
    # better to report nothing than to run to the end of the document
    html = "<p>Item 1A. Risk Factors</p>" + body("RISKS")

    assert "risk_factors" not in extract_sections(html_to_text(html))


def test_a_section_too_short_to_be_real_is_ignored():
    html = ("<p>Item 1A. Risk Factors</p><p>See our prior filing.</p>"
            "<p>Item 1B. Unresolved Staff Comments</p>")

    assert extract_sections(html_to_text(html)) == {}


def test_item_1b_is_optional():
    # most filings say "none" and omit it, so Item 2 has to close the section
    html = make_filing(
        rf="<p>Item 1A. Risk Factors</p>" + body("REALRISKS"),
        end="<p>Item 2. Properties</p>",
    )

    assert "REALRISKS" in extract_sections(html_to_text(html))["risk_factors"]


def test_mdna_is_found_independently_of_risk_factors():
    # a filing yielding one section and not the other is normal, not a failure
    html = ("<p>Item 7. Management's Discussion</p>" + body("DISCUSSION") +
            "<p>Item 8. Financial Statements</p>")

    sections = extract_sections(html_to_text(html))

    assert "DISCUSSION" in sections["mdna"]
    assert "risk_factors" not in sections


# - chunking

def test_chunks_cover_the_whole_section():
    text = "word " * 4000

    joined = "".join(chunk_text(text, size=1000, overlap=0))

    assert joined.replace(" ", "") == text.replace(" ", "")


def test_chunks_overlap_so_a_passage_is_not_split_in_half():
    chunks = chunk_text("word " * 2000, size=1000, overlap=200)

    # the tail of one chunk reappears at the head of the next
    assert len(chunks) > 1
    assert chunks[0][-100:].strip() in chunks[1]


def test_chunks_respect_the_size_limit():
    chunks = chunk_text("word " * 5000, size=1000, overlap=100)

    assert all(len(c) <= 1000 for c in chunks)


def test_a_short_section_is_one_chunk():
    assert chunk_text("a short section", size=1000) == ["a short section"]


def test_overlap_must_be_smaller_than_the_chunk():
    # otherwise the loop cannot advance and would never finish
    with pytest.raises(ValueError):
        chunk_text("text", size=100, overlap=100)


def test_chunking_empty_text_yields_nothing():
    assert chunk_text("") == []


# - locating the filing

def test_the_archive_path_drops_the_padding_and_dashes():
    # the archive uses a bare CIK and an accession with no dashes, unlike every
    # other EDGAR endpoint
    url = filing_url("0001601830", "0001601830-26-000039", "rxrx-20251231.htm")

    assert url.endswith("/data/1601830/000160183026000039/rxrx-20251231.htm")


def test_the_newest_annual_report_is_chosen(monkeypatch):
    import app.filings as filings

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"filings": {"recent": {
                "form": ["8-K", "10-Q", "10-K", "10-K"],
                "filingDate": ["2026-03-01", "2026-02-28", "2026-02-25", "2025-02-20"],
                "accessionNumber": ["a", "b", "c", "d"],
                "primaryDocument": ["w.htm", "x.htm", "y.htm", "z.htm"],
            }}}

    monkeypatch.setattr(filings, "_sec_get", lambda url: Resp())

    # the feed is newest first, so the first annual form is the current one
    assert latest_annual_filing("1")["accession"] == "c"


def test_a_foreign_issuer_annual_report_counts(monkeypatch):
    import app.filings as filings

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"filings": {"recent": {
                "form": ["6-K", "20-F"], "filingDate": ["2026-03-01", "2026-02-25"],
                "accessionNumber": ["a", "b"], "primaryDocument": ["x.htm", "y.htm"],
            }}}

    monkeypatch.setattr(filings, "_sec_get", lambda url: Resp())

    assert latest_annual_filing("1")["form"] == "20-F"


def test_a_company_with_no_annual_report_is_not_an_error(monkeypatch):
    import app.filings as filings

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"filings": {"recent": {"form": ["8-K"], "filingDate": ["x"],
                                           "accessionNumber": ["a"],
                                           "primaryDocument": ["b"]}}}

    monkeypatch.setattr(filings, "_sec_get", lambda url: Resp())

    assert latest_annual_filing("1") is None
