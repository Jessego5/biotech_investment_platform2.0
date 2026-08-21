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
SEC_ARCHIVE = ("https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"
               "{document}")

# the annual reports worth reading the narrative out of. 20-F is included for the
# same reason data_sources.py includes it: foreign issuers file one instead.
ANNUAL_FORMS = ("10-K", "20-F")

# how much text goes in one chunk, and how much of the previous chunk each one
# repeats. the overlap is so a risk that straddles a boundary is still wholly
# present in one of them, rather than split in half and matching neither.
CHUNK_CHARS = 3000
CHUNK_OVERLAP = 300

# a section shorter than this is a stub or a stray match rather than the thing
# itself. 500 was too generous: a 20-F matched a few hundred characters of Item 5
# and stored it as a Management's Discussion, which is worse than finding none.
MIN_SECTION_CHARS = 2000


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


def fetch_filing_text(cik, accession, document):
    """Download the filing and reduce it to plain text."""
    r = _sec_get(filing_url(cik, accession, document))
    r.raise_for_status()
    return html_to_text(r.text)


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
}


def bounds_for(form):
    """
    Which set of headings to look for. A 10-K and a 20-F share no section
    numbering, so reading one with the other's patterns finds nothing at all,
    which is what left every foreign issuer with no risk factors.
    """
    return _TWENTYF_BOUNDS if (form or "").upper().startswith("20-F") else _TENK_BOUNDS


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
_PART_REFERENCE = re.compile(r"\bPart\s+[IVX0-9]+\s*,\s*$", re.I)

_ITEM_REFERENCE = re.compile(r"\b(?:Item|Part)\s*[0-9IVX]+[A-C]?(?:\.[A-Z])?[.:,]?"
                             r"|\b[A-Z]\.(?=\s)", re.I)


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
    if _PART_REFERENCE.search(text[max(0, pos - 25):pos]):
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


def _real_headings(text, pattern):
    """The matches that are the heading itself, in document order."""
    return [p for p in _positions(pattern, text)
            if _is_heading(text, p)
            and not _is_cross_reference(text, p)
            and not _is_contents_entry(text, p)]


def _find_section(text, start_pattern, end_patterns):
    """
    Locate one section by its heading and the heading of whatever follows it.

    A heading appears several times: in the table of contents, as the section
    itself, in cross-references, and as a running page header repeated on every
    page of the section. Once those three are excluded the section's own heading
    is the first one left, so the earliest surviving start wins.
    """
    starts = _real_headings(text, start_pattern)
    ends = sorted(set(p for pattern in end_patterns
                      for p in _real_headings(text, pattern)))
    every_end = sorted(set(p for pattern in end_patterns
                           for p in _positions(pattern, text)))
    for start in starts:
        end = next((p for p in ends if p > start), None)
        # a closing heading may legitimately follow prose with no page number
        # before it, and ImmunityBio's every closing match sits before its real
        # heading. rather than lose the section, fall back to every match
        if end is None:
            end = next((p for p in every_end if p > start), None)
        # too short to be the section itself, so this start was a stray match
        if end is not None and (end - start) >= MIN_SECTION_CHARS:
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
    for name, (start_pattern, end_patterns) in bounds_for(form).items():
        found = _find_section(text, start_pattern, end_patterns)
        if found is None:
            continue
        body = text[found[0]:found[1]].strip()
        # too short to be the section itself, so this was a contents line
        if len(body) >= MIN_SECTION_CHARS:
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
