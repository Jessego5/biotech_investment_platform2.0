"""
Loads the FDA Purple Book: licensed biologic products and their regulatory
exclusivity.

This exists because the Orange Book's silence about biologics was being read as
a finding about a company's protection. Regeneron holds 22 licensed products and
the Orange Book has a row for none of them, so it came out looking the same as a
company that has never had anything approved. 27 companies in the universe move
out of that state on this source alone.

What is here and what is not:

- exclusivity, yes. Orphan exclusivity is populated for 570 of the 2,230
  products and is seven years of complete market protection, so it is real
  protection on its own. Reference-product and interchangeability exclusivity
  are present but sparse.
- patents, no. Biologic patent disputes run through the confidential BPCIA
  exchange rather than a public listing, so no equivalent of the Orange Book's
  patent file exists. A biologic with no exclusivity date is not unprotected;
  it is unlisted, and the two must not be reported the same way.

The published file is a monthly report in two parts: the changes for that month
first, then the whole database underneath. It is the second part this reads.

    python ingest_purple_book.py                  # download the current month
    python ingest_purple_book.py --file FILE.csv  # use a copy already saved
"""

import argparse
import csv
import datetime
import os
import re

import requests

from app.database import SessionLocal, init_db
from app.models import BiologicProduct, Company
from build_company_universe import identity, _norm

DOWNLOADS = "https://purplebooksearch.fda.gov/downloads"
USER_AGENT = os.environ.get("SEC_USER_AGENT", "biotech-agent contact@example.com")


def _iso(text):
    """"10/5/2018" -> "2018-10-05", so dates sort as strings like every other."""
    text = (text or "").strip()
    if not text or text == "-":
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y"):
        try:
            return datetime.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def latest_file_url():
    """
    The most recent monthly report. The download page lists every month ever
    published and they do not sort, so the year and month are read out of the
    filename rather than trusting the page order.
    """
    r = requests.get(DOWNLOADS, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    months = {m: i for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"], start=1)}
    best = None
    for url in re.findall(r'https://[^"\']*purplebook-search-[^"\']*\.csv', r.text):
        m = re.search(r"/(\d{4})/purplebook-search-([A-Za-z]+)-", url)
        if not m:
            continue
        key = (int(m.group(1)), months.get(m.group(2).lower(), 0))
        if best is None or key > best[0]:
            best = (key, url)
    if not best:
        raise RuntimeError("no Purple Book file found on the downloads page")
    return best[1]


def read_full_section(path):
    """
    The whole database, which is the second table in the file.

    Each report opens with the month's additions and updates under one header,
    then repeats the header and lists everything. Reading the first table would
    give one month of changes and quietly look like a complete answer.
    """
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    headers = [i for i, r in enumerate(rows) if r and r[0].strip() == "N/R/U"]
    if not headers:
        raise RuntimeError("no header row in the Purple Book file")
    start = headers[-1]
    header = [h.strip() for h in rows[start]]
    return [dict(zip(header, r)) for r in rows[start + 1:]
            if len(r) == len(header) and r[2].strip()]


def resolve(applicants, companies):
    """applicant -> ticker, on an exact identity only, as the Orange Book does."""
    by_first = {}
    for c in companies:
        key = _norm(c.name)
        if key:
            by_first.setdefault(key.split()[0], []).append(c)
    out = {}
    for name in applicants:
        key = _norm(name)
        if not key:
            continue
        for c in by_first.get(key.split()[0], ()):
            if identity(c.name, name) == "exact":
                out[name] = c.ticker
                break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="a copy of the monthly CSV already saved")
    args = ap.parse_args()

    path = args.file
    if not path:
        url = latest_file_url()
        print(f"downloading {url}")
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
        r.raise_for_status()
        path = "purple_book.csv"
        with open(path, "wb") as f:
            f.write(r.content)

    data = read_full_section(path)
    print(f"{len(data)} licensed biologic products")

    init_db()
    db = SessionLocal()
    try:
        companies = db.query(Company).all()
        resolved = resolve({d["Applicant"] for d in data}, companies)
        db.query(BiologicProduct).delete()

        for d in data:
            db.add(BiologicProduct(
                bla_number=d.get("BLA Number"),
                product_number=d.get("Product Number"),
                bla_type=d.get("BLA Type"),
                proprietary_name=d.get("Proprietary Name"),
                proper_name=d.get("Proper Name"),
                applicant=d.get("Applicant"),
                approval_date=_iso(d.get("Approval Date")),
                ref_product_exclusivity=_iso(d.get("Ref. Product Exclusivity Exp. Date")),
                orphan_exclusivity=_iso(d.get("Orphan Exclusivity Exp. Date")),
                interchangeable_exclusivity=_iso(
                    d.get("First Interchangeable Exclusivity Exp. Date")),
                company_ticker=resolved.get(d["Applicant"])))
        db.commit()

        linked = {t for t in resolved.values()}
        print(f"{len(resolved)} of {len({d['Applicant'] for d in data})} applicants "
              f"resolve; {len(linked)} companies hold a licensed biologic")
    finally:
        db.close()


if __name__ == "__main__":
    main()
