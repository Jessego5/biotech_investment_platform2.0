"""
This loads the FDA Purple Book: licensed biologic products and their regulatory
exclusivity. It exists because the Orange Book's silence about biologics was
being read as a finding about a company's protection, Regeneron holding 22
licensed products with an Orange Book row for none of them and so looking
identical to a company that has never had anything approved; 27 companies in the
universe move out of that state on this source alone. Exclusivity is here, with
orphan exclusivity populated for 570 of the 2,230 products and worth seven years
of complete market protection, so it is real protection on its own, while
reference-product and interchangeability exclusivity are present but sparse.
Patents are not here, because biologic patent disputes run through the
confidential BPCIA exchange rather than a public listing, so a biologic with no
exclusivity date is unlisted rather than unprotected and the two must not be
reported the same way. The published file is a monthly report in two parts, the
changes for that month first and the whole database underneath, and it is the
second part this reads. Run it with python ingest_purple_book.py, or --file
FILE.csv to use a copy already saved.
"""

import argparse
import csv
import datetime
import os
import re

import requests

from app.database import SessionLocal, init_db
from app.models import BiologicProduct, Company
from applicant_resolution import resolve_all

DOWNLOADS = "https://purplebooksearch.fda.gov/downloads"
USER_AGENT = os.environ.get("SEC_USER_AGENT", "biotech-agent contact@example.com")


def _iso(text):
    """"10/5/2018" -> "2018-10-05", so dates sort as strings like every other."""
    text = (text or "").strip()
    if not text or text == "-":
        return None
    # The file mixes formats. Most dates are "February 13, 1936", but roughly
    # half are "15-Jan-74", and a loader carrying only one of the two silently
    # drops the other half rather than failing: 45 of 2,230 approval dates
    # survived before both were handled.
    #
    # The two-digit year resolves through Python's pivot, so 69-99 reads as
    # 1900s and 00-68 as 2000s. That is right for every value here: approvals
    # run back to the 1930s and no exclusivity extends past 2068.
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d-%b-%y", "%m/%d/%Y", "%Y-%m-%d"):
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
        resolved = resolve_all(db, {d["Applicant"] for d in data}, companies)
        db.query(BiologicProduct).delete()

        for d in data:
            db.add(BiologicProduct(
                bla_number=d.get("BLA Number"),
                product_number=d.get("Product Number"),
                # "BLA Type" in older releases, "License Type" now. Reading the
                # old name gives a column of nulls and no error.
                bla_type=d.get("License Type") or d.get("BLA Type"),
                proprietary_name=d.get("Proprietary Name"),
                proper_name=d.get("Proper Name"),
                applicant=d.get("Applicant"),
                approval_date=_iso(d.get("Approval Date")),
                ref_product_exclusivity=_iso(d.get("Ref. Product Exclusivity Exp. Date")),
                orphan_exclusivity=_iso(d.get("Orphan Exclusivity Exp. Date")),
                interchangeable_exclusivity=_iso(
                    d.get("First Interchangeable Exclusivity Exp. Date")),
                patent_list_provided=(d.get("Patent List Provided", "")
                                      .strip().upper() == "YES"),
                company_ticker=(resolved.get(d["Applicant"]) or (None, None))[0],
                resolved_by=(resolved.get(d["Applicant"]) or (None, None))[1]))
        db.commit()

        linked = {t for t in resolved.values()}
        print(f"{len(resolved)} of {len({d['Applicant'] for d in data})} applicants "
              f"resolve; {len(linked)} companies hold a licensed biologic")
    finally:
        db.close()


if __name__ == "__main__":
    main()
