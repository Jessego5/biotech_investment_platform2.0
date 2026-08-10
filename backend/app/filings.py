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

# a section shorter than this is almost certainly a cross-reference or a stub
# ("see Item 1A"), not the section itself
MIN_SECTION_CHARS = 500


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
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&[a-zA-Z]+;|&#\d+;", "", text)
    return re.sub(r"\s+", " ", text).strip()


# the headings that bound each section. a 10-K has no markup saying "this is the
# risk factors section", so the only way to find one is to look for its heading
# and the heading of whatever comes next.
_SECTION_BOUNDS = {
    "risk_factors": (
        r"Item\s*1A[.\s\-–—]*Risk\s*Factors",
        # 1B is often absent (it is usually "none"), so Item 2 is the fallback end
        [r"Item\s*1B[.\s\-–—]*Unresolved", r"Item\s*1C[.\s\-–—]*Cyber",
         r"Item\s*2[.\s\-–—]*Propert"],
    ),
    "mdna": (
        r"Item\s*7[.\s\-–—]*Management.{0,3}s\s*Discussion",
        [r"Item\s*7A[.\s\-–—]*Quantitative",
         r"Item\s*8[.\s\-–—]*Financial\s*Statements"],
    ),
}


def _positions(pattern, text):
    return [m.start() for m in re.finditer(pattern, text, re.I)]


def _find_section(text, start_pattern, end_patterns):
    """
    Locate one section by its heading and the heading of whatever follows it.

    A heading appears several times: in the table of contents, as the section
    itself, and in cross-references like "see Item 1A" elsewhere. Position cannot
    tell them apart, so each is paired with the nearest closing heading after it
    and the longest span wins, since only the real section runs to hundreds of
    thousands of characters.
    """
    best = None
    starts = _positions(start_pattern, text)
    ends = sorted(p for pattern in end_patterns for p in _positions(pattern, text))
    for start in starts:
        # the nearest closing heading after this one. a cross-reference usually
        # has none, which is how Fate's and AbbVie's filings drop theirs.
        end = next((p for p in ends if p > start), None)
        if end is None:
            continue
        # a span containing another copy of its own heading is a contents line
        # reaching across the document, not a section. Recursion's contents does
        # not list Item 1B, so without this its contents line pairs with the real
        # closing heading and swallows everything in between.
        if any(start < other < end for other in starts):
            continue
        if best is None or (end - start) > (best[1] - best[0]):
            best = (start, end)
    return best


def extract_sections(text):
    """
    Pull the narrative sections out of a filing's text.

    Returns {section: text} containing only the sections that were found and are
    long enough to be real. A filing that doesn't yield a section is not an error:
    plenty of companies incorporate risk factors by reference, or use headings
    this doesn't recognise, and a missing section is better than a wrong one.
    """
    sections = {}
    for name, (start_pattern, end_patterns) in _SECTION_BOUNDS.items():
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
