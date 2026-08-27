"""
Builds the alias table: every other name one of our companies is known by.

Corporate identity is the join that the FDA data needs and cannot supply. An
approved drug is held by "Janssen Pharmaceuticals" or "Pharmacyclics LLC", not
by Johnson & Johnson or AbbVie, and no spelling rule reaches across that gap
because the names have nothing in common. Matching only on exact identity left
45% of listed patents attached to nobody.

Exhibit 21 to the 10-K is the answer, and it is a source we already use.
"Subsidiaries of the Registrant" is the company's own statement of what it owns,
filed annually, and it names exactly the entities the FDA files are written
against. Johnson & Johnson lists 840 of them including Janssen and Actelion;
AbbVie lists 33 including Pharmacyclics and Allergan.

Two things were tried first and are worth recording as rejected:

- GLEIF, the global LEI register, publishes real parent/child relationships and
  resolves "Janssen Pharmaceuticals, Inc." to "Johnson & Johnson" correctly. On
  the applicants we actually need it recovered 2 of 40, because the FDA writes
  "TAKEDA PHARMACEUTICALS USA INC" where GLEIF holds "Takeda Pharmaceuticals
  U.S.A., Inc.", and several entities that do have an LEI report no parent.
- a looser name rule, which is what admitted Tesla and Nova Scotia Health
  Authority elsewhere in this project.

The exhibit is found by its EDGAR document TYPE and never by filename. Pfizer
files it as "pfe-exh21x12312025x10k.htm", so a filename pattern silently reports
that Pfizer does not file one.

    python build_aliases.py              # every company in the universe
    python build_aliases.py --limit 20   # a few, to try it out
"""

import argparse
import os
import re
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
WORKERS = 6

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

NOISE = re.compile(
    r"^(exhibit|subsidiar|name|jurisdiction|state|country|entity|list of|"
    r"the following|percent|ownership|organi[sz]ation|registrant|omitted|"
    r"table of|item \d)", re.I)


def _get(url, attempts=4):
    last = None
    for attempt in range(attempts):
        try:
            r = requests.get(url, headers=HEADERS, timeout=45)
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(1.2 * (attempt + 1))
            continue
        if r.status_code in (403, 429) and attempt < attempts - 1:
            time.sleep(1.5 * (attempt + 1))
            continue
        return r
    raise last


def latest_annual(cik):
    """(accession, form) for the most recent 10-K or 20-F, or None."""
    r = _get(SUBMISSIONS.format(cik=cik))
    if r.status_code != 200:
        return None
    recent = r.json().get("filings", {}).get("recent", {})
    for i, form in enumerate(recent.get("form", [])):
        if form in ("10-K", "20-F"):
            return recent["accessionNumber"][i], form
    return None


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
    text = re.sub(r"&(nbsp|#160|amp|#38);", " ", text)
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
        if not ENTITY.search(line):
            continue
        # a line that BEGINS with a corporate form is a name split across table
        # cells, not a name: "Corporation, a Delaware company" is the tail of
        # something whose first half is on the row above.
        if TRUNCATED.match(line):
            continue
        out.append(line)
    return out


def for_company(company):
    """(ticker, cik, accession, [names]) or None."""
    try:
        found = latest_annual(company.cik)
        if not found:
            return None
        accession, _ = found
        doc = exhibit_21_document(company.cik, accession)
        if not doc:
            return None
        base = ARCHIVE.format(cik=int(company.cik), acc=accession.replace("-", ""))
        r = _get(f"{base}/{doc}")
        if r.status_code != 200:
            return None
        return company.ticker, company.cik, accession, parse_subsidiaries(r.text)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only this many companies")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    try:
        companies = db.query(Company).all()
        if args.limit:
            companies = companies[:args.limit]
        print(f"reading Exhibit 21 for {len(companies)} companies "
              f"({WORKERS} at a time)...\n")

        results, done, without = [], 0, 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(for_company, c) for c in companies]
            for fut in as_completed(futures):
                done += 1
                got = fut.result()
                if got and got[3]:
                    results.append(got)
                else:
                    without += 1
                if done % 100 == 0:
                    print(f"  ...{done}/{len(companies)}, "
                          f"{sum(len(r[3]) for r in results)} names so far")

        # an alias claimed by two companies is not usable: it would attach an
        # approved drug to whichever happened to be written last. Historical
        # ownership makes this real, since a subsidiary sold between two filers
        # appears in both their exhibits.
        owners = {}
        for ticker, cik, accession, names in results:
            for name in names:
                owners.setdefault(_norm(name), set()).add(ticker)
        ambiguous = {k for k, v in owners.items() if len(v) > 1}

        db.query(Alias).filter(Alias.source == "ex21").delete()
        written = 0
        for ticker, cik, accession, names in results:
            seen = set()
            for name in names:
                key = _norm(name)
                if not key or key in ambiguous or key in seen:
                    continue
                seen.add(key)
                db.add(Alias(cik=cik, company_ticker=ticker, alias=name,
                             alias_key=key, source="ex21", accession=accession))
                written += 1
        db.commit()

        print(f"\n{len(results)} companies filed an exhibit we could read, "
              f"{without} did not")
        print(f"{written} aliases written; {len(ambiguous)} names dropped as "
              f"claimed by more than one company")
    finally:
        db.close()


if __name__ == "__main__":
    main()
