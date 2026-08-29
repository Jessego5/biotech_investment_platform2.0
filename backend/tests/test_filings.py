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
                         bounds_for, ANNUAL_FORMS, _FORTYF_BOUNDS, _TWENTYF_BOUNDS, _TENK_BOUNDS,
                         latest_annual_filing, MIN_SECTION_CHARS)


def body(marker, length=6000):
    """Filler long enough to count as a real section."""
    return f" {marker} " + "word " * (length // 5)


# - turning filing HTML into text

def test_a_word_split_by_inline_markup_stays_one_word():
    # CRISPR Therapeutics' 10-K styles the middle of a word, and replacing every
    # tag with a space turned "Risk Factors" into "Ris k Factors", which stopped
    # the heading matching and silently lost the section
    assert "Risk Factors" in html_to_text("<p>Item 1A. Ris<span>k</span> Factors</p>")


def test_hex_html_entities_are_stripped_like_decimal_ones():
    # Medicenna's 20-F writes every space as "&#xa0;" and its quotes as
    # "&#x201c;". Only decimal entities were stripped, so the hex ones survived
    # into the text and split every heading, leaving the filing with no sections
    text = html_to_text("<p>3.D.&#xa0;&#xa0;Risk&#xa0;Factors&#x201d;</p>")

    assert "&#x" not in text
    assert "Risk Factors" in text


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
    html = (# a contents block lists consecutive items. Recursion's omits Item
            # 1B, which is what let its contents line reach the real one
            "<p>Item 1. Business 9</p><p>Item 1A. Risk Factors 46</p>"
            "<p>Item 2. Properties 92</p><p>Item 3. Legal Proceedings 93</p>"
            "<p>Some other part of the filing</p>" + body("FILLER") +
            # a real heading follows a page marker, which is what tells it apart
            # from a citation in running prose
            "<p>Table of Contents</p><p>Item 1A. Risk Factors</p>" + body("REALRISKS") +
            "<p>Item 1B. Unresolved Staff Comments</p>")

    sections = extract_sections(html_to_text(html))

    assert "REALRISKS" in sections["risk_factors"]
    assert "FILLER" not in sections["risk_factors"]


def test_a_page_header_repeated_through_the_section_is_not_its_start():
    # Supernus repeats "ITEM 1A. RISK FACTORS." as a page header on all 46 pages
    # of the section. Every candidate span then contained what looked like its
    # own heading, so only the fragment after the last page header survived and
    # the section stored as 2,963 characters against a true 199,757
    pages = "".join("<p>%d Table of Contents</p><p>Item 1A. Risk Factors</p>%s"
                    % (n, body("PAGE%d" % n, 3000)) for n in range(2, 8))
    html = ("<p>Item 1. Business 4</p><p>Item 1A. Risk Factors 33</p>"
            "<p>Item 2. Properties 72</p>"
            "<p>1 Table of Contents</p><p>Item 1A. Risk Factors</p>"
            + body("REALRISKS") + pages
            + "<p>Item 1B. Unresolved Staff Comments</p>")

    rf = extract_sections(html_to_text(html))["risk_factors"]

    # the section runs from the first real heading through every page of it
    assert "REALRISKS" in rf and "PAGE7" in rf


def test_a_cross_reference_is_not_a_closing_heading():
    # Galmed's 20-F says "See also Item 4. Information on the Company" eight
    # times inside its risk factors. Taking the first of those as the end closed
    # the section early, at 86,396 characters against a true 231,662
    html = ("<p>Item 1. Business 4</p><p>Item 1A. Risk Factors 33</p>"
            "<p>Item 2. Properties 72</p>"
            "<p>1 Table of Contents</p><p>Item 1A. Risk Factors</p>"
            + body("REALRISKS")
            + "<p>as we discuss, see Item 1B. Unresolved Staff Comments</p>"
            + body("MORERISKS")
            + "<p>92 Item 1B. Unresolved Staff Comments</p>")

    rf = extract_sections(html_to_text(html))["risk_factors"]

    assert "REALRISKS" in rf and "MORERISKS" in rf


def test_a_part_reference_with_a_comma_is_not_a_heading():
    from app.filings import _is_heading, _is_cross_reference

    # ImmunityBio points at its accounts as "in Part II, Item 8. Financial
    # Statements" three times before the real closing heading, and there is no
    # cue word anywhere in it. Gilead does the same with "including Part I,
    # Item 1A. Risk Factors", which was being read as the section itself
    for text in ("the notes thereto in Part II, Item 8. Financial Statements",
                 "this Annual Report, including Part I, Item 1A. Risk Factors"):
        pos = text.index("Item")
        assert _is_heading(text, pos) is True      # the old rule allowed it
        assert _is_cross_reference(text, pos) is True


def test_a_structural_part_heading_has_no_comma():
    from app.filings import _is_cross_reference

    text = "PART II Item 7. Management's Discussion"
    assert _is_cross_reference(text, text.index("Item")) is False


def test_the_full_stops_in_an_item_number_do_not_end_a_sentence():
    from app.filings import _is_cross_reference

    # ProQR cites "described in Part I, Item 3.D: Risk Factors" and Sanofi
    # "discussed under Item 3. Key Information D. Risk Factors". Reading those
    # full stops as the end of a sentence let both citations pass as headings
    for text in ("including those described in Part I, Item 3.D: Risk Factors",
                 "those discussed under Item 3. Key Information D. Risk Factors"):
        assert _is_cross_reference(text, text.rindex("Risk Factors")) is True


def test_a_sentence_ending_before_a_heading_is_not_a_reference():
    from app.filings import _is_cross_reference

    # Bio-Path's real heading follows "publicly disclosed pursuant to rules of
    # the SEC.", where the cue word belongs to the sentence before it
    text = "publicly disclosed pursuant to rules of the SEC. ITEM 1A. RISK FACTORS"
    assert _is_cross_reference(text, text.index("ITEM 1A")) is False


def test_a_citation_in_running_prose_is_not_a_heading():
    # Pfizer's 10-K names its own section twenty-nine times, nearly all of them
    # mid-sentence and inside the section itself, which left every real span
    # looking like it contained its own heading
    from app.filings import _is_heading

    text = "see the Item 1A. Risk Factors section for more"
    pos = text.index("Item 1A")
    assert _is_heading(text, pos) is False


def test_a_citation_opening_a_sentence_is_not_a_heading():
    from app.filings import _is_heading

    # "See" is capitalised, so the lowercase-prose rule alone read it as a page
    # header. OKYO's 20-F closes sub-items with "See Item 5. Operating and
    # Financial Review", one of them inside Item 5, which rejected the real
    # section for appearing to contain its own heading
    text = "D. Trend Information See Item 5. Operating and Financial Review"
    assert _is_heading(text, text.index("Item 5")) is False


def test_a_heading_after_a_page_marker_is_a_heading():
    from app.filings import _is_heading

    # a page number, and a running header, are what precede a real heading
    for prefix in ("...of the foregoing. 43 ", "...report. 70 Table of Contents "):
        text = prefix + "Item 1A. Risk Factors"
        assert _is_heading(text, text.index("Item 1A")) is True


def test_a_short_stray_match_is_not_stored_as_a_section():
    # a 20-F matched a few hundred characters of Item 5 and stored it as a
    # Management's Discussion, which is worse than reporting none
    html = ("<p>Item 5. Operating and Financial Review</p><p>Brief note.</p>"
            "<p>Item 6. Directors</p>")

    assert extract_sections(html_to_text(html), "20-F") == {}


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


# - making a partial extraction detectable

def test_section_lengths_are_recorded_not_just_which_were_found(db):
    # "found" is not enough. Pfizer's risk factors extracted as 10k characters
    # against a normal 200k: present by any flag, and wrong. the length is the
    # only signal, so it has to be stored rather than only printed.
    from app.models import Company, Filing
    from embed_filings import store_filing

    company = Company(ticker="AAA", name="Alpha")
    db.add(company)
    db.flush()
    meta = {"form": "10-K", "filed": "2026-02-25", "accession": "a", "document": "d.htm"}
    store_filing(db, company, meta, "x" * 900000,
                 {"risk_factors": "r" * 240000, "mdna": "m" * 40000})
    db.commit()

    filing = db.query(Filing).one()
    assert filing.risk_factors_chars == 240000
    assert filing.mdna_chars == 40000


def test_a_missing_section_records_zero_length_not_null(db):
    # zero says "read it, found none of this"; null would be indistinguishable
    # from a filing written before lengths were recorded
    from app.models import Company, Filing
    from embed_filings import store_filing

    company = Company(ticker="AAA", name="Alpha")
    db.add(company)
    db.flush()
    meta = {"form": "20-F", "filed": "2026-03-10", "accession": "a", "document": "d.htm"}
    store_filing(db, company, meta, "x" * 500000, {"mdna": "m" * 20000})
    db.commit()

    filing = db.query(Filing).one()
    assert filing.risk_factors_chars == 0
    assert filing.mdna_chars == 20000


def _tenk(body):
    """A 10-K skeleton with enough bulk that a real section clears the floor."""
    return ("Item 1. Business " + "The company develops therapies. " * 40
            + body
            + "Item 1A. Risk Factors " + "Our business faces risks. " * 400)


def test_the_intellectual_property_section_is_found_by_its_heading():
    body = ("Intellectual Property We own issued patents covering our lead "
            "candidate and license further rights from a university. " * 40
            + "Competition The market is competitive. " * 80)
    got = extract_sections(_tenk(body), "10-K")
    assert got["intellectual_property"].startswith("Intellectual Property")
    assert "license further rights" in got["intellectual_property"]


def test_the_phrase_in_running_prose_is_not_the_section():
    # this is the failure that mattered: the phrase appears far more often in
    # the risk factors than the business section, and a case-insensitive search
    # took "the intellectual property landscape is highly dynamic" for a heading
    # at CRISPR Therapeutics, Beam, Alnylam and Sarepta alike
    body = ("We note that the intellectual property landscape around gene "
            "editing is highly dynamic and third parties may hold rights. " * 60)
    assert "intellectual_property" not in extract_sections(_tenk(body), "10-K")


def test_inline_xbrl_is_not_the_section():
    # "IntellectualPropertyMember2025-01-01..." is tag soup, and without a word
    # boundary CRISPR extracted three thousand characters of it
    body = ("IntellectualPropertyMember2025-01-012025-12-310001674416us-gaap:"
            "AccumulatedOtherComprehensiveIncomeMember " * 60)
    assert "intellectual_property" not in extract_sections(_tenk(body), "10-K")


def test_an_upper_case_heading_is_still_a_heading():
    body = ("INTELLECTUAL PROPERTY We rely on a combination of patents and "
            "trade secrets to protect our candidates. " * 40
            + "Competition The market is competitive. " * 80)
    got = extract_sections(_tenk(body), "10-K")
    assert got["intellectual_property"].startswith("INTELLECTUAL PROPERTY")


def test_a_heading_after_item_1a_is_not_the_business_section():
    # "Intellectual Property and Market Exclusivity Risks" is a risk-factors
    # heading. IP sits inside Item 1, and Item 1A always follows it
    text = ("Item 1. Business " + "We develop therapies. " * 200
            + "Item 1A. Risk Factors " + "Risks abound. " * 100
            + "Intellectual Property and Market Exclusivity Risks We may not "
              "be able to protect our rights. " * 60
            + "Competition is fierce. " * 80)
    assert "intellectual_property" not in extract_sections(text, "10-K")


def test_a_40f_uses_its_own_headings():
    # a 40-F wraps the Canadian Annual Information Form and MD&A, which carry no
    # item numbers at all, so the 10-K patterns find nothing in one
    assert bounds_for("40-F") is _FORTYF_BOUNDS
    assert bounds_for("20-F") is _TWENTYF_BOUNDS
    assert bounds_for("10-K") is _TENK_BOUNDS


def test_the_canadian_annual_report_sections_are_found():
    text = ("Annual Information Form " + "Corporate structure and history. " * 60
            + "Risk Factors An investment in the Common Shares involves a high "
              "degree of risk and should be considered speculative. " * 40
            + "Dividends and Distributions We have never paid a dividend. " * 60
            + "Management's Discussion and Analysis For the year ended December 31. "
            + "Results of operations are discussed below. " * 60
            + "Consolidated Financial Statements " + "Balance sheet. " * 60)
    got = extract_sections(text, "40-F")
    assert got["risk_factors"].startswith("Risk Factors")
    assert "speculative" in got["risk_factors"]
    assert "Dividends and Distributions" not in got["risk_factors"]
    assert got["mdna"].startswith("Management's Discussion and Analysis")


def test_40f_is_an_annual_form():
    # Aurora Cannabis, Cybin and NervGen file one and had no filing stored at all
    assert "40-F" in ANNUAL_FORMS


def test_a_subsection_may_be_short():
    # the 2,000 floor exists to reject a contents line and was applied to a
    # subsection too. Monopar's intellectual property section is 1,795
    # characters and was thrown away for it — a company with one licensed asset
    # has little to say and says it briefly
    body = ("Intellectual Property We hold one issued US patent covering our lead "
            "candidate and license further rights from a university. " * 12
            + "Competition The market is competitive. " * 80)
    got = extract_sections(_tenk(body), "10-K")
    assert "intellectual_property" in got
    assert 600 < len(got["intellectual_property"]) < 2000


def test_a_contents_line_is_still_rejected():
    # the lower floor must not start admitting the table of contents
    body = "Intellectual Property 14 Competition 15 Manufacturing 16 " * 2
    assert "intellectual_property" not in extract_sections(_tenk(body), "10-K")


def test_a_20f_finds_its_ip_section_inside_item_4():
    # a 20-F has no Item 1A. Its risk factors are Item 3 and its business
    # description Item 4, so bounding only on "before Item 5" matched
    # risk-factor prose sitting earlier in the document
    text = ("Item 3. Key Information Risk Factors "
            + "Intellectual Property If we are unable to obtain and maintain patent "
              "protection our competitors may commercialise our technology. " * 40
            + "Item 4. Information on the Company Business Overview "
            + "Intellectual Property We own issued patents covering our candidate "
              "and license rights from a university. " * 30
            + "Competition The market is competitive. " * 60
            + "Item 5. Operating and Financial Review " + "Results follow. " * 200)
    got = extract_sections(text, "20-F")
    assert got["intellectual_property"].startswith("Intellectual Property We own")
    assert "unable to obtain" not in got["intellectual_property"]
