"""
This file pulls the narrative part of a company's annual report out of EDGAR: the
Risk Factors and the Management's Discussion, which are where a company says in
its own words what could go wrong and how it reads its own numbers. The structured
figures already come from XBRL; this is the part of a filing that only exists as
prose, and it is what lets the app answer "what does this company say are its
biggest risks?" instead of only counting things.

It is deliberately separate from data_sources.py. That file reads figures, which
are exact and mechanical. This one reads documents, which are messy: a 10-K is a
few megabytes of HTML with no markup identifying its sections, so the sections
have to be found by their headings and the headings appear more than once. Keeping
the fragile part in its own file makes it obvious which of the two is which.
"""

import re

from .data_sources import _sec_get

SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
FILING_INDEX = ("https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"
                "{accession_dashed}-index.htm")
SEC_ARCHIVE = ("https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"
               "{document}")

# the annual reports worth reading the narrative out of. 20-F is included for the
# same reason data_sources.py includes it: foreign issuers file one instead.
ANNUAL_FORMS = ("10-K", "20-F", "40-F")

# how much text goes in one chunk, and how much of the previous chunk each one
# repeats. the overlap is so a risk that straddles a boundary is still wholly
# present in one of them, rather than split in half and matching neither.
CHUNK_CHARS = 3000
CHUNK_OVERLAP = 300

# a section shorter than this is a stub or a stray match rather than the thing
# itself. 500 was too generous: a 20-F matched a few hundred characters of Item 5
# and stored it as a Management's Discussion, which is worse than finding none.
MIN_SECTION_CHARS = 2000

# A subsection is not an Item and cannot be held to an Item's length. The floor
# above exists to reject a table-of-contents line, which is a few dozen
# characters before the next entry — it does not need to be 2,000 to do that.
# Intellectual property runs to 1,795 characters at Monopar and was thrown away
# for being short, when a company with one licensed asset has little to say and
# says it briefly.
MIN_SUBSECTION_CHARS = 600
SUBSECTIONS = {"intellectual_property"}


def latest_annual_filing(cik):
    """
    Metadata for the most recent annual report, or None if there isn't one.

    The submissions feed lists filings newest first, so the first annual form is
    the current one.
    """
    r = _sec_get(SEC_SUBMISSIONS.format(cik=cik))
    if r.status_code == 404:
        return None
    r.raise_for_status()
    recent = r.json().get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    for i, form in enumerate(forms):
        if form in ANNUAL_FORMS:
            return {
                "form": form,
                "filed": recent["filingDate"][i],
                "accession": recent["accessionNumber"][i],
                "document": recent["primaryDocument"][i],
            }
    return None


def filing_url(cik, accession, document):
    """Where the filing's primary document lives in EDGAR's archive."""
    # the archive path drops the zero padding from the CIK and the dashes from
    # the accession number, unlike everywhere else that uses them
    return SEC_ARCHIVE.format(cik=int(cik), accession=accession.replace("-", ""),
                              document=document)


def exhibit_documents(cik, accession):
    """
    The EX-99 documents attached to a filing, in the order EDGAR lists them.

    A 40-F needs them. It is a cover form under the Canada-US multijurisdictional
    system, and the narrative it reports is the Canadian Annual Information Form
    and MD&A, filed as exhibits rather than written into the form itself.

    Which exhibit holds what cannot be inferred from its number. Cybin files the
    Annual Information Form as EX-99.1 and the MD&A as EX-99.3; Aurora Cannabis
    files certifications as EX-99.1 through EX-99.3; NervGen's are named nothing
    at all. So every EX-99 is fetched and the headings decide, which is what the
    section finder already does.
    """
    r = _sec_get(FILING_INDEX.format(cik=int(cik),
                                     accession=accession.replace("-", ""),
                                     accession_dashed=accession))
    if r.status_code != 200:
        return []
    docs = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= 4 and cells[3].upper().startswith("EX-99"):
            link = re.search(r'href="([^"]+)"', row)
            if link:
                docs.append(link.group(1).split("/")[-1])
    return docs


def fetch_filing_text(cik, accession, document, form="10-K"):
    """
    Download the filing and reduce it to plain text.

    For a 40-F that means the exhibits as well as the form, joined into one
    document. The section finder then works over the whole submission and picks
    up Risk Factors and MD&A wherever the filer put them. Certifications and
    financial statements come along too; they are short or carry none of the
    headings, so they cost nothing.
    """
    r = _sec_get(filing_url(cik, accession, document))
    r.raise_for_status()
    text = html_to_text(r.text)
    if form != "40-F":
        return text
    parts = [text]
    for doc in exhibit_documents(cik, accession):
        try:
            er = _sec_get(filing_url(cik, accession, doc))
            if er.status_code == 200:
                parts.append(html_to_text(er.text))
        except Exception:
            # one unreadable exhibit must not cost the rest of the filing
            continue
    return "\n\n".join(parts)


# tags that end a line of text. everything else is inline styling that can sit in
# the middle of a word, so only these become a space when the markup is removed.
_BLOCK_TAGS = (r"p|div|br|hr|tr|td|th|table|tbody|thead|li|ul|ol|"
               r"h[1-6]|section|article|header|footer|blockquote")


def html_to_text(html):
    """
    Strip a filing down to readable text. Crude on purpose: filings are tables and
    styling around ordinary prose, and all this needs is the prose in order.

    What cannot be crude is which tags become a space. Filings split words across
    inline markup, so replacing every tag with one turns "Ris<span>k</span>
    Factors" into "Ris k Factors" and the heading stops matching, which is how
    CRISPR Therapeutics' risk factors went missing.
    """
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)

    # Inline XBRL first. A modern filing carries its machine-readable facts in
    # the same document as its prose, inside <ix:hidden> and a header block that
    # are never displayed to a reader. Left in, they arrive as a wall of
    # "jnj:PatentsAndTrademarksMember2025-12-28" — which is not merely noise:
    # it matched "patent" twenty-four times inside Johnson & Johnson's Item 1
    # and produced "IntellectualPropertyMember" as a candidate heading at CRISPR
    # Therapeutics. It also inflates every position the section finder works
    # with, so an Item boundary is measured against text a reader never sees.
    text = re.sub(r"(?is)<ix:hidden.*?</ix:hidden>", " ", text)
    text = re.sub(r"(?is)<ix:header.*?</ix:header>", " ", text)
    # elements the filer explicitly hides carry the same kind of content
    text = re.sub(r'(?is)<div[^>]*style="[^"]*display:\s*none[^"]*"[^>]*>.*?</div>',
                  " ", text)
    # a block tag ends a line, so it becomes a space
    text = re.sub(rf"(?i)</?({_BLOCK_TAGS})\b[^>]*>", " ", text)
    # everything else is inline and is removed without one, keeping words whole
    text = re.sub(r"<[^>]+>", "", text)
    # a non-breaking space is a real space; the rest carry no meaning worth
    # embedding, and decoding them would only reintroduce markup-like characters
    text = re.sub(r"&nbsp;|&#160;|&#[xX]0*[aA]0;", " ", text)
    # hex entities as well as decimal. filers write both, and Medicenna's 20-F
    # uses hex throughout, so leaving them in wrapped every heading in "&#xa0;"
    # and none of the section patterns matched
    text = re.sub(r"&[a-zA-Z]+;|&#\d+;|&#[xX][0-9a-fA-F]+;", "", text)
    return re.sub(r"\s+", " ", text).strip()


# the headings that bound each section. a 10-K has no markup saying "this is the
# risk factors section", so the only way to find one is to look for its heading
# and the heading of whatever comes next.
_TENK_BOUNDS = {
    "risk_factors": (
        r"Item\s*1A[.:\s\-–—]*Risk\s*Factors",
        # 1B is often absent (it is usually "none"), so Item 2 is the fallback end
        [r"Item\s*1B[.:\s\-–—]*Unresolved", r"Item\s*1C[.:\s\-–—]*Cyber",
         r"Item\s*2[.:\s\-–—]*Propert"],
    ),
    "mdna": (
        r"Item\s*7[.:\s\-–—]*Management.{0,3}s\s*Discussion",
        [r"Item\s*7A[.:\s\-–—]*Quantitative",
         r"Item\s*8[.:\s\-–—]*Financial\s*Statements"],
    ),
    # Where a company states what IP it owns and, crucially, what it licenses
    # in. For most of this universe that is the only patent information that
    # exists anywhere: the Orange Book covers approved small molecules, and 85%
    # of these companies have nothing approved. It is also the only place the
    # licensed-in question is answerable at all — a patent assigned to a
    # university and exclusively licensed to the company shows the university as
    # assignee everywhere else.
    #
    # Unlike the others this is a subsection of Item 1 rather than a numbered
    # item, so it has no "Item N" heading and the thing that follows it varies by
    # company. The end patterns are the subsections that usually come next, and
    # Item 1A closes it for anyone who orders them differently, since IP always
    # sits inside Item 1 and Item 1A always follows.
    "intellectual_property": (
        # Case-sensitive, which nothing else here needs to be. Every other
        # section is found by an "Item N" heading that cannot appear in running
        # prose; this one is an ordinary noun phrase, and a case-insensitive
        # search finds it far more often in the risk factors than in the
        # business section: "the intellectual property landscape around gene
        # editing is highly dynamic" outranked the real heading for CRISPR
        # Therapeutics, Beam, Alnylam and Sarepta alike. A heading is title case
        # or upper case; the prose is not.
        #
        # The word boundary matters too: inline XBRL writes
        # "IntellectualPropertyMember2025-01-01..." and without it CRISPR
        # extracted three thousand characters of tag soup.
        # "Patents" belongs here and its absence was a real gap. Johnson &
        # Johnson heads the section that way — its own contents page reads
        # "Raw materials 3  Patents 3  Trademarks 3" — and so do Theravance,
        # Vericel and Gyre. "Intellectual Property" is the clinical-stage
        # convention; the older and more diversified filers write "Patents", and
        # looking only for the former read those companies as having no patent
        # disclosure at all, which for J&J is plainly false.
        #
        # It is safe here in a way it is not in a 20-F, because a 10-K's section
        # must sit before Item 1A and a 20-F has no Item 1A to bound against.
        # The optional leading "Something and " matters more than it looks.
        # Filers combine the heading — Colgate writes "Trademarks and Patents",
        # Alx Oncology "Licensing and Intellectual Property" — and matching only
        # the tail lands the start on a lowercase "and", which reads as running
        # prose and is thrown out. Anchoring at the first word of the heading
        # keeps it a heading.
        r"(?-i:(?:[A-Z][A-Za-z]+\s+and\s+)?"
        r"(?:INTELLECTUAL\s+PROPERTY|Intellectual\s+Property|PATENTS|Patents|"
        r"PROPRIETARY\s+RIGHTS|Proprietary\s+Rights|Trademarks))\b",
        [r"Government(?:al)?\s*Regulation", r"Competition",
         r"Manufacturing", r"Human\s*Capital", r"Employees",
         r"Sales\s*and\s*Marketing", r"Commerciali[sz]ation",
         # what follows Patents in the older layout
         r"Trademarks", r"Seasonality", r"Raw\s+Materials",
         r"Item\s*1A[.:\s\-–—]*Risk\s*Factors"],
        # and it has to sit inside Item 1. The phrase appears far more often in
        # the risk factors than in the business section — "the intellectual
        # property landscape around gene editing is highly dynamic" — and the
        # search is case-insensitive, so prose matches as readily as a heading.
        r"Item\s*1A[.:\s\-–—]*Risk\s*Factors",
    ),
}

# a 20-F is numbered differently: risk factors sit inside Item 3 (Key
# Information) and the operating review is Item 5, so none of the 10-K headings
# appear at all. BioNTech's filing does not even write "Item 3.D", it just heads
# the section "Risk Factors", which is why the start pattern here is the bare
# phrase. That is loose on its own, and safe only because a section still has to
# be the longest span that does not contain another copy of its own heading: the
# contents line pairs with the contents copy of Item 4 and is far too short, and
# the cross-references later in the document have no closing heading after them.
_TWENTYF_BOUNDS = {
    "risk_factors": (
        r"Risk\s*Factors",
        [r"Item\s*4[.:\s\-–—]*Information\s*on\s*the\s*Company",
         r"Item\s*4[.:\s\-–—]*Information"],
    ),
    "mdna": (
        r"Item\s*5[.:\s\-–—]*Operating\s*and\s*Financial",
        [r"Item\s*6[.:\s\-–—]*Directors", r"Item\s*7[.:\s\-–—]*Major\s*Shareholders"],
    ),
    # A foreign issuer describes its IP under Item 4B, Business Overview, and
    # frequently heads it "Patents" rather than "Intellectual Property" —
    # Abivax uses that word sixteen times and the other twice. There is no Item
    # 1A here to bound against, so Item 5 does it: Item 4 always precedes it.
    "intellectual_property": (
        # Tried in order. "Patents" is back — its absence cost Novo Nordisk,
        # which heads the section exactly that — but it goes last, because it is
        # also an ordinary word.
        [r"(?-i:(?:[A-Z][A-Za-z]+\s+and\s+)?"
         r"(?:INTELLECTUAL\s+PROPERTY|Intellectual\s+Property|Proprietary\s+Rights))\b",
         r"(?-i:(?:[A-Z][A-Za-z]+\s+and\s+)?(?:PATENTS|Patents))\b"],
        [r"Competition", r"Government(?:al)?\s*Regulation", r"Manufacturing",
         r"Employees", r"Human\s*Capital", r"Organi[sz]ational\s+Structure",
         r"Propert(?:y|ies),?\s+Plants?\s+and\s+Equipment",
         r"Item\s*4A[.:\s\-–—]*Unresolved",
         # Item 5's own sub-headings, which close Item 4 as reliably as Item 5
         # does and survive where it does not: AstraZeneca's "Item 5" appears
         # only inside a run-together navigation string, so nothing closed the
         # section and it ran 36,000 characters into the sales commentary.
         r"Geographical\s+Review", r"Operating\s+Results",
         r"Item\s*5[.:\s\-–—]*Operating\s*and\s*Financial"],
        r"Item\s*5[.:\s\-–—]*Operating\s*and\s*Financial",
        r"Item\s*4[.:\s\-–—]*Information\s*on\s*the\s*Company",
    ),
}


# A 40-F is numbered differently again, because it is not really a form of its
# own: it wraps the Canadian Annual Information Form and MD&A, which use their
# own section names and no item numbers at all. The headings below are the ones
# an AIF actually uses, and the ends are the sections that conventionally follow
# Risk Factors in one.
_FORTYF_BOUNDS = {
    "risk_factors": (
        r"Risk\s*Factors",
        [r"Dividends\s+and\s+Distributions", r"Dividend\s+Policy",
         r"Description\s+of\s+(?:the\s+)?(?:Share\s+)?Capital\s+Structure",
         r"Market\s+for\s+Securities", r"Directors\s+and\s+(?:Executive\s+)?Officers",
         r"Legal\s+Proceedings", r"Material\s+Contracts", r"Transfer\s+Agents?",
         r"Interests?\s+of\s+Experts", r"Additional\s+Information"],
    ),
    "mdna": (
        r"Management.{0,3}s\s+Discussion\s+and\s+Analysis",
        [r"Consolidated\s+Financial\s+Statements",
         r"Report\s+of\s+Independent", r"Interests?\s+of\s+Experts",
         r"CERTIFICATION"],
    ),
    # A 40-F carries its business description in the Annual Information Form
    # attached as an exhibit, which is laid out like a prospectus rather than
    # like an Item. There are no item numbers to bound against, so the headings
    # of the parts around it do the work.
    "intellectual_property": (
        [r"(?-i:(?:[A-Z][A-Za-z]+\s+and\s+)?"
         r"(?:INTELLECTUAL\s+PROPERTY|Intellectual\s+Property|Proprietary\s+Rights))\b",
         r"(?-i:(?:[A-Z][A-Za-z]+\s+and\s+)?(?:PATENTS|Patents))\b"],
        [r"Competition", r"Government(?:al)?\s*Regulation", r"Manufacturing",
         r"Employees", r"Human\s*Capital", r"Risk\s*Factors",
         r"Legal\s+Proceedings", r"Dividends\s+and\s+Distributions",
         r"Description\s+of\s+(?:the\s+)?(?:Share\s+)?Capital\s+Structure",
         r"Market\s+for\s+Securities",
         r"Directors\s+and\s+(?:Executive\s+)?Officers"],
    ),
}


def bounds_for(form):
    """
    Which set of headings to look for. The three forms share no section
    numbering, so reading one with another's patterns finds nothing at all,
    which is what left every foreign issuer with no risk factors.
    """
    form = (form or "").upper()
    if form.startswith("20-F"):
        return _TWENTYF_BOUNDS
    if form.startswith("40-F"):
        return _FORTYF_BOUNDS
    return _TENK_BOUNDS


def _positions(pattern, text):
    return [m.start() for m in re.finditer(pattern, text, re.I)]


# words that introduce a cross-reference rather than a section. lowercase prose
# is already caught by the rule below; these are the ones that open a sentence
# and so arrive capitalised.
_CITATION_WORDS = {"see", "refer", "under", "within", "per"}

# the same idea a few words further back, for "Refer to Part I, Item 1A", where
# the word immediately before the heading is "I," rather than the cue. only
# unambiguous cues belong here: "under", "within" and "per" are ordinary
# prepositions in this prose ("under the Investors News section", "under U.S.
# law") and reading them as cross-references drops real headings.
_CITATION_CUES = {"see", "refer", "pursuant", "described", "discussed"}

# an item heading, used to tell a contents entry from a real one
_ITEM_HEADING = re.compile(r"Item\s*\d+[A-C]?[.:\s]", re.I)

# a reference to an item by number. the full stops inside one ("Item 3.D.") are
# numbering rather than the end of a sentence, so they are removed before asking
# whether a sentence ended.
# a lone capital letter and a full stop is a lettered sub-item ("D. Risk
# Factors"), which is numbering too. Sanofi's citation reads "discussed under
# Item 3. Key Information D. Risk Factors", and both parts have to go.
# "Part II," immediately before a heading, which introduces a reference
# "Part II," with a comma, or a "Part II." that a lowercase word runs into.
# The comma alone was the tell, and Precision BioSciences and Structure
# Therapeutics both point at their own management discussion with a full stop
# instead — "identified in Part I. Item 1A. Risk Factors and Part II. Item 7.
# Management's Discussion". The conjunction in front is what separates that
# from the structural "PART II" that really does head Item 7: a part heading
# does not follow the word "and".
_PART_REFERENCE = re.compile(
    r"\bPart\s+[IVX0-9]+\s*(?:,\s*$|\.\s*$)"
    r"|\b(?:and|or|in|to|under|of|see)\s+Part\s+[IVX0-9]+\s*[.,]\s*$", re.I)

# A heading inside quotation marks is a filing naming one of its sections.
# Telix writes 'can be found in "Item 5. Operating and financial review and
# prospects" of this Annual Report', which started the management discussion
# 475,000 characters early.
_QUOTED = re.compile(r"[\"“‘']\s*$")

_ITEM_REFERENCE = re.compile(r"\b(?:Item|Part)\s*[0-9IVX]+[A-C]?(?:\.[A-Z])?[.:,]?"
                             r"|\b[A-Z]\.(?=\s)", re.I)


# 25 characters of capitals, with at least three letters, so "ITEM 5. OPERATING
# AND FINANCIAL" qualifies and an acronym in ordinary prose does not.
_SHOUTED = re.compile(r"(?:[A-Z0-9][^a-z]{0,3}){3,}[^a-z]*$")


def _is_heading(text, pos):
    """
    Whether a match is the heading itself rather than prose referring to it.

    Filings cite their own sections inline, and large ones do it constantly:
    Pfizer's 10-K contains "Item 1A. Risk Factors" twenty-nine times, nearly all
    of them mid-sentence and most of them inside the section they name. Those
    references defeat the span rules, because every candidate span then contains
    another copy of its own heading and only an isolated fragment survives, which
    is how Pfizer's risk factors extracted as ten thousand characters.

    The tell is the word before it. A reference follows ordinary prose ("see
    the", "in the section titled"); a heading follows a page number or a page
    header, so the preceding word is capitalised or numeric. Testing the
    character rather than the word is not enough: Recursion's real heading
    follows the page header "Table of Contents" and so ends in a lowercase "s".

    A citation opening a sentence is the exception, because "See" is capitalised
    and so reads as a page header by that rule alone. OKYO's 20-F closes several
    sub-items with "See Item 5. Operating and Financial Review", one of which
    sits inside Item 5 itself, and taking it for a heading rejects the real
    section for containing its own heading.
    """
    # A heading set in capitals needs no evidence from what precedes it. The
    # rule below reads the word before, and a heading that follows a one-line
    # stub section follows prose: Marker Therapeutics' Item 5 comes straight
    # after "ITEM 4A. UNRESOLVED STAFF COMMENTS Not applicable", so the word
    # before the heading is "applicable" and the whole management discussion
    # was thrown away. Running prose is not written in capitals.
    if _SHOUTED.match(text[pos:pos + 25]):
        return True
    before = text[max(0, pos - 80):pos].rstrip()
    if not before:
        return True
    last_word = before.rsplit(" ", 1)[-1]
    if last_word.lower().strip(",.;:") in _CITATION_WORDS:
        return False
    # entirely lowercase letters means running prose, so this is a citation
    return not (last_word.isalpha() and last_word.islower())


def _is_cross_reference(text, pos):
    """
    Whether a cue word a few words back makes this a reference.

    Supernus writes "Refer to Part I, Item 1A Risk Factors" three times before
    the section itself, and the word immediately before the heading is "I,",
    which reads as a page marker. The cue has to be in the same sentence: these
    words appear in ordinary prose too, and Bio-Path's real heading follows
    "publicly disclosed pursuant to rules of the SEC.", which is not a reference
    to anything. The full stops inside an item number do not end a sentence,
    which is what ProQR's "described in Part I, Item 3.D: Risk Factors" turns on.
    """
    # "in Part II, Item 8. Financial Statements" is a reference with no cue word
    # in it at all. the comma is the tell: a structural "PART II ITEM 7A" heading
    # does not have one. ImmunityBio points at its accounts this way three times
    # before the real closing heading.
    if _PART_REFERENCE.search(text[max(0, pos - 40):pos]):
        return True
    if _QUOTED.search(text[max(0, pos - 4):pos]):
        return True
    window = text[max(0, pos - 45):pos]
    cue = None
    for word in re.finditer(r"[A-Za-z]+", window):
        if word.group(0).lower() in _CITATION_CUES:
            cue = word
    if cue is None:
        return False
    return "." not in _ITEM_REFERENCE.sub(" ", window[cue.end():])


def _is_contents_entry(text, pos, span=130):
    """
    Whether this is a line in the table of contents.

    A contents entry is followed by the next item's entry; a real heading is
    followed by prose. This is what tells the two apart, since both can sit
    behind a page number.
    """
    return len(_ITEM_HEADING.findall(text[pos:pos + span])) >= 2


# a heading followed by its page number, which is what a contents line looks
# like once the layout is gone: "Patents 3 Trademarks 3 Seasonality 3"
# A contents line LISTS things: name, page, name, page. One page number after a
# heading is a page break landing there — Vericel's real "Patents and
# Proprietary Rights" is followed by "9 Table of Contents" — so two pairs are
# required before calling it a contents line.
# "Patents and Licenses, etc. 82 5.D Trend Information 82 5.E" — a 20-F numbers
# its contents entries, so what follows the page number is "5.D" and not a
# capital letter. Takeda and Galapagos both had their contents line read as the
# section because of it.
_PAGE_NUMBERED = re.compile(r"\s\d{1,3}\s+(?:[A-Z][A-Za-z]|\d+\.[A-Z]|[A-Z]\.)")


def _is_contents_line(text, pos, span=90):
    """
    Whether a match is an entry in the table of contents rather than the
    section itself.

    _is_contents_entry catches the numbered kind, by looking for two "Item N"
    headings close together. A section listed by name has no item number:
    Johnson & Johnson's contents reads "Raw materials 3 Patents 3 Trademarks 3",
    and the "Patents" in it is followed by a page number and the next entry. A
    real heading is followed by prose.
    """
    return len(_PAGE_NUMBERED.findall(text[pos:pos + span])) >= 2


# A heading phrase running on into "below" or "above": capitalised words, with
# the small joining words a title is allowed, and then the direction.
_POINTS_ELSEWHERE = re.compile(
    r"[A-Z][\w,.]*(?:\s+(?:and|or|of|the|to|in|this|[A-Z0-9][\w,.]*)){0,16}"
    r"\s+(?:below|above|elsewhere)\b")


def _points_elsewhere(text, pos):
    """
    Whether the heading is the tail of a cross-reference rather than a heading.

    _is_cross_reference looks backwards for a cue word, and finds nothing when
    the cue is far enough back: Sanofi writes "see Patents, Intellectual
    Property and Other Rights below", and by the time the match starts the
    "see" is out of the window. What gives it away is in front of it. A real
    heading is followed by the section; this one is followed by the rest of its
    own sentence, and a heading is never followed by the word "below".

    "Elsewhere" is the same move over a longer phrase: GPCR's risk factors point
    at "Item 7. Management's Discussion and Analysis of Financial Condition and
    Results of Operations and elsewhere in this Annual Report", and taking that
    for the heading started the management discussion inside the risk factors
    and ran it 605,000 characters, which is most of the filing.
    """
    return _POINTS_ELSEWHERE.match(text[pos:pos + 180]) is not None


# Three numbers in the first 40 characters after the heading. Aurora Cannabis'
# "Patents 189 6 (197) 2 Software 749 3,406" is a row of an intangible-assets
# note, not the start of a description of a patent estate.
_TABLE_ROW = re.compile(r"^[^a-z]{0,40}?(?:\(?\d[\d,.]*\)?\s+){3}")

# A glossary entry defines the term rather than heading a section. Bright Minds
# lists "Patents and Patent Applications" among its defined terms, and the
# giveaway is the word that follows shortly after.
_DEFINITION = re.compile(r"^.{0,80}?\bmeans\b", re.S)


# The name of an institution, not a heading. Cybin's filing names the United
# Kingdom Intellectual Property Office while listing its patent applications.
_NAMES_A_BODY = re.compile(r"^(?:Intellectual\s+Property|INTELLECTUAL\s+PROPERTY)"
                           r"\s+(?:Office|Organi[sz]ation|Court|Tribunal|Appeal)")


def _is_table_or_glossary(text, pos):
    """Whether the match heads a financial table or a list of defined terms."""
    if _NAMES_A_BODY.match(text[pos:pos + 60]):
        return True
    after = text[pos:pos + 120]
    after = after[len(re.match(r"[^\s]*(?:\s+[A-Z][^\s]*)*", after).group(0)):]
    return bool(_TABLE_ROW.match(after) or _DEFINITION.match(after))


def _real_headings(text, pattern):
    """The matches that are the heading itself, in document order."""
    return [p for p in _positions(pattern, text)
            if _is_heading(text, p)
            and not _is_cross_reference(text, p)
            and not _is_contents_entry(text, p)
            and not _is_contents_line(text, p)
            and not _points_elsewhere(text, p)
            and not _is_table_or_glossary(text, p)]


def _find_section(text, start_pattern, end_patterns, limit=None,
                  floor=MIN_SECTION_CHARS, after=None):
    """
    Locate one section by its heading and the heading of whatever follows it.

    A heading appears several times: in the table of contents, as the section
    itself, in cross-references, and as a running page header repeated on every
    page of the section. Once those three are excluded the section's own heading
    is the first one left, so the earliest surviving start wins.
    """
    starts = _real_headings(text, start_pattern)
    if limit is not None:
        starts = [p for p in starts if p < limit]
    if after is not None:
        starts = [p for p in starts if p > after]
    ends = sorted(set(p for pattern in end_patterns
                      for p in _real_headings(text, pattern)))
    every_end = sorted(set(p for pattern in end_patterns
                           for p in _positions(pattern, text)))
    for start in starts:
        # The nearest closing heading, and then the next one if that is too
        # close to be real. A word that also heads a section appears inside the
        # prose of the section before it — "a combination of patents,
        # trademarks, trade secrets" sits 168 characters into Treace's
        # intellectual property section — and taking the first match and giving
        # up when it proved too near threw away sections that a later, real
        # heading would have closed properly.
        end = next((p for p in ends if p > start and (p - start) >= floor), None)
        if end is None:
            end = next((p for p in ends if p > start), None)
        # a closing heading may legitimately follow prose with no page number
        # before it, and ImmunityBio's every closing match sits before its real
        # heading. rather than lose the section, fall back to every match
        if end is None:
            end = next((p for p in every_end if p > start), None)
        # too short to be the section itself, so this start was a stray match
        if end is not None and (end - start) >= floor:
            return (start, end)
    return None


def extract_sections(text, form="10-K"):
    """
    Pull the narrative sections out of a filing's text, using the headings that
    the given form actually uses.

    Returns {section: text} containing only the sections that were found and are
    long enough to be real. A filing that doesn't yield a section is not an error:
    plenty of companies incorporate risk factors by reference, or use headings
    this doesn't recognise, and a missing section is better than a wrong one.
    """
    sections = {}
    for name, spec in bounds_for(form).items():
        # a section may declare a heading it must appear before, which is how a
        # subsection of Item 1 says so: it has no item number of its own, and
        # its name reads as ordinary prose everywhere else in the filing
        start_pattern, end_patterns = spec[0], spec[1]
        must_precede = spec[2] if len(spec) > 2 else None
        must_follow = spec[3] if len(spec) > 3 else None
        limit = None
        if must_precede:
            after = _real_headings(text, must_precede)
            if after:
                limit = after[0]
        # When a section is bracketed by two Item headings, the first match of
        # each is the wrong pair: a contents page lists them adjacently, so
        # Sanofi's Item 4 and Item 5 came out 232 characters apart and Novartis
        # got Item 5 BEFORE Item 4. The real pair is the one that brackets the
        # most document, because that is what an Item actually is.
        if must_precede and must_follow:
            lows = _real_headings(text, must_follow)
            highs = _real_headings(text, must_precede)
            best = max(((hi - lo, lo, hi) for lo in lows for hi in highs if hi > lo),
                       default=None)
            if best:
                _, lo, hi = best
                limit = hi
        # and where it must start after. A 20-F puts its risk factors in Item 3
        # and its business description in Item 4, so "must precede Item 5" alone
        # lets the section match risk-factor prose sitting earlier in the
        # document — which is how "If we are unable to obtain and maintain
        # patent protection" was read as a description of a patent estate.
        floor_pos = None
        if must_follow:
            before = _real_headings(text, must_follow)
            if before:
                floor_pos = before[0]
            if must_precede:
                lows = before
                highs = _real_headings(text, must_precede)
                best = max(((hi - lo, lo) for lo in lows for hi in highs if hi > lo),
                           default=None)
                if best:
                    floor_pos = best[1]
        floor = MIN_SUBSECTION_CHARS if name in SUBSECTIONS else MIN_SECTION_CHARS
        # A start may be a list, tried in order of how unambiguous it is.
        # "Intellectual Property" is a heading and almost nothing else;
        # "Patents" is also an ordinary word that a filing about patents uses
        # constantly. Preferring the first means AstraZeneca and Sanofi stop
        # matching "Patents covering our products are routinely challenged",
        # which is a sentence, while Novo Nordisk still resolves through the
        # fallback because "Patents" is genuinely what it heads the section.
        patterns = start_pattern if isinstance(start_pattern, (list, tuple)) \
            else [start_pattern]
        found = None
        for candidate in patterns:
            found = _find_section(text, candidate, end_patterns, limit, floor,
                                  floor_pos)
            if found is not None:
                break
        if found is None:
            continue
        body = text[found[0]:found[1]].strip()
        # too short to be the section itself, so this was a contents line
        if len(body) >= floor:
            sections[name] = body
    return sections


def chunk_text(text, size=CHUNK_CHARS, overlap=CHUNK_OVERLAP):
    """
    Split a section into overlapping pieces small enough to embed usefully.

    Whole sections are far too long to embed as one vector: a biotech's risk
    factors run to hundreds of thousands of characters, and averaging all of that
    into one vector describes nothing. Chunks are cut at a space where possible so
    a piece doesn't start or end mid-word.
    """
    if overlap >= size:
        raise ValueError("overlap must be smaller than the chunk size")
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        # back up to the last space so the chunk ends on a word, unless that
        # would throw away most of the chunk
        if end < len(text):
            space = text.rfind(" ", start + size // 2, end)
            if space != -1:
                end = space
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks
