"""
This builds the alias table, every other name one of our companies is known by.
Corporate identity is the join the FDA data needs and cannot supply, because an
approved drug is held by "Janssen Pharmaceuticals" or "Pharmacyclics LLC" and
not by Johnson & Johnson or AbbVie, and no spelling rule reaches across that gap
when the names have nothing in common; matching on exact identity alone left 45%
of listed patents attached to nobody. Exhibit 21 to the 10-K is the answer and is
a source we already use, being the company's own annual statement of what it
owns, named against exactly the entities the FDA files are written for: Johnson
& Johnson lists 840 including Janssen and Actelion, AbbVie lists 33 including
Pharmacyclics and Allergan. Two approaches were tried first and rejected. GLEIF,
the global LEI register, resolves "Janssen Pharmaceuticals, Inc." correctly but
recovered only 2 of the 40 applicants we actually need, because the FDA writes
"TAKEDA PHARMACEUTICALS USA INC" where GLEIF holds "Takeda Pharmaceuticals
U.S.A., Inc.", and several entities with an LEI report no parent at all; a
looser name rule is what admitted Tesla and Nova Scotia Health Authority
elsewhere in this project. The exhibit is found by its EDGAR document type and
never by filename, since Pfizer files it as "pfe-exh21x12312025x10k.htm" and a
filename pattern silently reports that Pfizer does not file one. Run it with
python build_aliases.py, or --limit 20 to try it on a few.
"""

import argparse
import html
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from app.database import SessionLocal, init_db
from app.models import Alias, Company
from build_company_universe import _norm

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "biotech-agent you@example.com")
HEADERS = {"User-Agent": SEC_USER_AGENT}
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}"
WORKERS = 3

# SEC asks for ten requests a second or fewer, and each company costs three, so
# a pool of workers hitting it flat out goes over. The first run did, and the
# throttled responses were read as "this company files no exhibit": 638 of 746
# companies came back empty, including Johnson & Johnson, whose exhibit I had
# already read by hand.
#
# Two things follow. Requests are spaced globally rather than per worker, well
# under the stated limit. And when SEC does push back it blocks the address for
# minutes, not for one request, so the pause has to be shared too: a worker that
# sees a 429 stands the whole pool down instead of each retrying into the same
# wall and deepening the block.
MIN_INTERVAL = 0.25
COOLDOWN = 120.0
_last_request = [0.0]
_resume_after = [0.0]
_throttle = threading.Lock()


class FetchFailed(Exception):
    """The request never completed, which is not the same as an empty answer."""

# corporate forms that mark a line as naming an entity rather than describing
# one. An Exhibit 21 is a two-column table of name and jurisdiction, and the
# jurisdictions are what has to be kept out.
FORMS = (r"inc|incorporated|corp|corporation|co|company|llc|l\.l\.c|ltd|limited|"
         r"plc|gmbh|ag|a\.g|s\.a|sa|b\.v|bv|n\.v|nv|pty|pte|s\.r\.l|srl|s\.p\.a|"
         r"spa|kk|k\.k|oy|ab|aps|a\/s|sas|sarl|s\.a\.r\.l|lp|l\.p|llp|holdings|"
         r"pharmaceuticals|pharma|therapeutics|biosciences|laboratories|labs")
ENTITY = re.compile(rf"\b({FORMS})\b\.?\s*$", re.I)

# lines that are headings, column labels or boilerplate rather than a subsidiary
# the jurisdiction clause some exhibits append to the name itself
JURISDICTION = re.compile(
    r",?\s+an?\s+[A-Z][A-Za-z .]{2,28}\s+"
    r"(corporation|company|limited liability company|partnership|entity)\s*$", re.I)

# a fragment left when a name is split across table cells
TRUNCATED = re.compile(rf"^({FORMS})\b", re.I)

# everything up to and including the LAST corporate form on the line, which
# drops a trailing jurisdiction that was never separated from the name
TRAILING_FORM = re.compile(rf"^(.*\b(?:{FORMS})\b\.?)", re.I)

NOISE = re.compile(
    r"^(exhibit|subsidiar|name|jurisdiction|state|country|entity|list of|"
    r"the following|percent|ownership|organi[sz]ation|registrant|omitted|"
    r"table of|item \d)", re.I)


def _get(url, attempts=5):
    """
    GET, spaced against SEC's rate limit and raising when it never succeeded.

    Returning the throttled response was the bug: a 429 has a body and a status
    and reads as an answer at every call site, so 638 companies were recorded as
    filing no Exhibit 21 when the truth was that we never asked successfully.
    """
    last = None
    for attempt in range(attempts):
        with _throttle:
            now = time.monotonic()
            wait = max(_resume_after[0] - now,
                       MIN_INTERVAL - (now - _last_request[0]))
            if wait > 0:
                time.sleep(wait)
            _last_request[0] = time.monotonic()
        try:
            r = requests.get(url, headers=HEADERS, timeout=45)
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code in (403, 429) or r.status_code >= 500:
            last = FetchFailed(f"{r.status_code} for {url}")
            if r.status_code in (403, 429):
                # stand the whole pool down, not just this worker
                with _throttle:
                    _resume_after[0] = max(_resume_after[0],
                                           time.monotonic() + COOLDOWN)
            else:
                time.sleep(2.0 * (attempt + 1))
            continue
        return r
    raise FetchFailed(str(last))


def annual_filings(cik, years):
    """
    [(accession, fiscal_year)] for this company's annual reports, newest first.

    Every year within the window, not just the latest. Exhibit 21 is a snapshot
    of what the company owned when it filed, so a subsidiary acquired and then
    dissolved appears only in the filings between those two dates. Reading the
    latest alone silently drops exactly the acquisitions this table exists for.
    """
    r = _get(SUBMISSIONS.format(cik=cik))
    if r.status_code != 200:
        return []
    recent = r.json().get("filings", {}).get("recent", {})
    dates = recent.get("filingDate") or []
    out = []
    for i, form in enumerate(recent.get("form", [])):
        if form in ("10-K", "20-F"):
            filed = dates[i] if i < len(dates) else ""
            out.append((recent["accessionNumber"][i],
                        int(filed[:4]) if filed[:4].isdigit() else None))
            if len(out) >= years:
                break
    return out


def exhibit_21_document(cik, accession):
    """
    The EX-21 document name, found by its declared type.

    EDGAR's filing index page carries a Type column, and that is authoritative.
    Guessing from the filename fails on Pfizer, whose exhibit is named
    "pfe-exh21x12312025x10k.htm", and a guess that fails looks exactly like a
    company that files no exhibit at all.
    """
    base = ARCHIVE.format(cik=int(cik), acc=accession.replace("-", ""))
    r = _get(f"{base}/{accession}-index.htm")
    if r.status_code != 200:
        return None
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= 4 and cells[3].upper().startswith("EX-21"):
            link = re.search(r'href="([^"]+)"', row)
            if link:
                return link.group(1).split("/")[-1]
    return None


def parse_subsidiaries(text):
    """
    Entity names out of an Exhibit 21.

    The exhibits are free-form: some are HTML tables, some are plain text, and
    the columns vary. Rather than parse the layout, this keeps lines that end in
    a corporate form, which is what separates "Janssen Pharmaceuticals, Inc."
    from "Delaware".
    """
    text = re.sub(r"<[^>]+>", "\n", text)
    # decode entities into real characters rather than blanking them. Replacing
    # "&amp;" with a space put THREE spaces in the middle of "Merck Sharp &amp;
    # Dohme LLC", and the run-of-spaces split below then cut it into "Merck
    # Sharp" and "Dohme LLC". Merck's own flagship subsidiary was unreachable
    # that way, and with it the 401 trials it leads.
    text = html.unescape(text)
    # a non-breaking space is a space, not a separator
    text = text.replace("\xa0", " ")
    # Splitting on newlines alone is not enough. AbbVie files its exhibit as
    # scanned images with the text hidden behind them in white one-point type,
    # so a whole page arrives as one run: "AbbVie Finance Corporation Delaware
    # AbbVie Global Inc. Delaware AbbVie Holdco Inc. Delaware". The entries are
    # separated by runs of spaces and nothing else, and a line-based reader sees
    # one line that ends in a jurisdiction and keeps none of it.
    text = re.sub(r"[ \t]{2,}", "\n", text)
    out = []
    for line in text.splitlines():
        line = " ".join(line.split()).strip(" .,;|")
        # many exhibits append the jurisdiction to the name rather than putting
        # it in its own column: "Acrivon Securities Corporation, a Massachusetts
        # corporation". The trailing clause is not part of what the entity is
        # called, and leaving it on stops the name matching anything.
        line = JURISDICTION.sub("", line).strip(" .,;|")
        if not (4 < len(line) < 120) or NOISE.match(line):
            continue
        # the jurisdiction usually trails the name with no punctuation between
        # them, so keep everything up to and including the last corporate form.
        # Greedy, not lazy: "Forest Laboratories Ireland Limited" must not be cut
        # back to "Forest Laboratories" at the first form word it contains.
        trimmed = TRAILING_FORM.match(line)
        if not trimmed:
            continue
        line = trimmed.group(1).strip(" .,;|")
        if not (4 < len(line) < 120):
            continue
        # a line that BEGINS with a corporate form is a name split across table
        # cells, not a name: "Corporation, a Delaware company" is the tail of
        # something whose first half is on the row above.
        if TRUNCATED.match(line):
            continue
        out.append(line)
    return out


def for_company(company, years):
    """
    [(ticker, cik, accession, fiscal_year, [names])], one entry per annual
    filing that carried a readable exhibit, or "failed" when the company's
    filing list could not be fetched at all.

    Those two outcomes are kept apart deliberately. Folding a failed request into
    "no exhibit" is what made the first run look complete while missing Johnson &
    Johnson, AbbVie, Pfizer and Merck.
    """
    try:
        filings = annual_filings(company.cik, years)
    except FetchFailed:
        return "failed"
    except Exception:
        return []
    out = []
    for accession, year in filings:
        try:
            doc = exhibit_21_document(company.cik, accession)
            if not doc:
                continue
            base = ARCHIVE.format(cik=int(company.cik),
                                  acc=accession.replace("-", ""))
            r = _get(f"{base}/{doc}")
            if r.status_code != 200:
                continue
            names = parse_subsidiaries(r.text)
            if names:
                out.append((company.ticker, company.cik, accession, year, names))
        except FetchFailed:
            # one unreachable year must not cost the other nine
            continue
        except Exception:
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only this many companies")
    ap.add_argument("--years", type=int, default=10,
                    help="how many annual filings back to read (default 10)")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    try:
        companies = db.query(Company).all()
        if args.limit:
            companies = companies[:args.limit]
        print(f"reading up to {args.years} years of Exhibit 21 for "
              f"{len(companies)} companies ({WORKERS} at a time)...\n")

        # written as we go, not banked to the end. A run that is killed part way
        # through used to lose everything it had done, which is how the first
        # multi-hour crawl produced nothing at all.
        db.query(Alias).filter(Alias.source == "ex21").delete()
        db.commit()

        done = failed = without = written = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(for_company, c, args.years) for c in companies]
            for fut in as_completed(futures):
                done += 1
                got = fut.result()
                if got == "failed":
                    failed += 1
                    continue
                if not got:
                    without += 1
                    continue
                # one row per (company, name, year). The same subsidiary in ten
                # filings is ten rows, which is what carries the year range that
                # an as-of-date view needs.
                seen = set()
                for ticker, cik, accession, year, names in got:
                    for name in names:
                        key = _norm(name)
                        if not key or (key, year) in seen:
                            continue
                        seen.add((key, year))
                        db.add(Alias(cik=cik, company_ticker=ticker, alias=name,
                                     alias_key=key, source="ex21",
                                     accession=accession, fiscal_year=year))
                        written += 1
                if done % 25 == 0:
                    db.commit()
                    print(f"  ...{done}/{len(companies)}, {written} rows")
        db.commit()

        # an alias claimed by two companies is not usable: it would attach an
        # approved drug to whichever happened to be written last. Reading many
        # years makes this more likely, not less, since a subsidiary sold between
        # two filers legitimately appears in both their histories.
        rows = db.query(Alias.alias_key, Alias.company_ticker).filter(
            Alias.source == "ex21").distinct().all()
        owners = {}
        for key, ticker in rows:
            owners.setdefault(key, set()).add(ticker)
        ambiguous = [k for k, v in owners.items() if len(v) > 1]
        for chunk in (ambiguous[i:i + 400] for i in range(0, len(ambiguous), 400)):
            db.query(Alias).filter(Alias.source == "ex21",
                                   Alias.alias_key.in_(chunk)).delete(
                                       synchronize_session=False)
        db.commit()

        kept = db.query(Alias).filter(Alias.source == "ex21").count()
        firms = db.query(Alias.company_ticker).filter(
            Alias.source == "ex21").distinct().count()
        print(f"\n{done - without - failed} companies filed a readable exhibit, "
              f"{without} did not")
        if failed:
            print(f"{failed} could not be checked at all, these say nothing "
                  f"about the company and should be re-run")
        print(f"{kept} alias rows over {firms} companies; "
              f"{len(ambiguous)} names dropped as claimed by more than one")
    finally:
        db.close()


if __name__ == "__main__":
    main()
