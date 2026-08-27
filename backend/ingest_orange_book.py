"""
Loads the FDA Orange Book: approved drug products, the patents listed against
them, and their regulatory exclusivity.

The join is the point. Products, patents and exclusivity all key on the
application number, so they meet on an exact integer and no name matching is
involved. Name matching enters once, at the edge: deciding which of our
companies an applicant belongs to. That is the same judgement the trial sponsor
matching makes, so it uses the same rule rather than a second one.

What this can and cannot answer, because it decides how the result must be read:

- it covers approved SMALL MOLECULES. Biologics are licensed under a BLA and
  appear in the Purple Book, not here, so Regeneron and Moderna have no row
- a company with no approved product has no row either, which is most of a
  universe of clinical-stage biotech
- neither absence means the company lacks patents. Reported as a boolean this
  would read as "no moat" for 85% of the universe, nearly all of it wrong

    python ingest_orange_book.py                 # download and load
    python ingest_orange_book.py --from-dir DIR  # use files already unzipped
"""

import argparse
import csv
import datetime
import io
import os
import zipfile

import requests

from app.database import SessionLocal, init_db
from app.models import (ApprovedProduct, ProductPatent, ProductExclusivity,
                        Company)
from build_company_universe import identity, MEDICAL_SIC, _norm

# the Orange Book data files, published monthly
ORANGE_BOOK = "https://www.fda.gov/media/76860/download?attachment"
USER_AGENT = os.environ.get("SEC_USER_AGENT", "biotech-agent contact@example.com")


def _iso(text):
    """
    "Aug 24, 2026" -> "2026-08-24", so dates sort as strings.

    The trial dates already stored are ISO, and a column that mixed the two
    formats would compare wrongly rather than fail, which is the worse outcome.
    """
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _flag(value):
    """The files write a flag as "Y" or empty."""
    return (value or "").strip().upper() == "Y"


def read_files(directory):
    """The three files as lists of dicts, keyed by their tilde-separated header."""
    out = {}
    for name in ("products", "patent", "exclusivity"):
        path = os.path.join(directory, f"{name}.txt")
        with open(path, encoding="utf-8", errors="replace") as f:
            out[name] = list(csv.DictReader(f, delimiter="~"))
    return out


def download(directory):
    """Fetch and unzip the published data files."""
    print(f"downloading {ORANGE_BOOK}")
    r = requests.get(ORANGE_BOOK, headers={"User-Agent": USER_AGENT}, timeout=120)
    r.raise_for_status()
    zipfile.ZipFile(io.BytesIO(r.content)).extractall(directory)
    print(f"  unzipped into {directory}")


def resolve_applicants(applicants, companies):
    """
    applicant name -> ticker, using the trial sponsor matching rule.

    Only an exact identity is accepted. A near match is a guess about which
    company an approved drug belongs to, and attributing somebody else's
    approved product is a worse error than leaving it unattributed.
    """
    by_first = {}
    for c in companies:
        key = _norm(c.name)
        if key:
            by_first.setdefault(key.split()[0], []).append(c)

    resolved = {}
    for name in applicants:
        key = _norm(name)
        if not key:
            continue
        for c in by_first.get(key.split()[0], ()):
            if identity(c.name, name) == "exact":
                resolved[name] = c.ticker
                break
    return resolved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dir", help="use files already unzipped here")
    args = ap.parse_args()

    directory = args.from_dir
    if not directory:
        directory = "orange_book"
        os.makedirs(directory, exist_ok=True)
        download(directory)

    files = read_files(directory)
    print(f"{len(files['products'])} products, {len(files['patent'])} patent rows, "
          f"{len(files['exclusivity'])} exclusivity rows")

    init_db()
    db = SessionLocal()
    try:
        companies = db.query(Company).all()
        applicants = {p["Applicant_Full_Name"] for p in files["products"]}
        resolved = resolve_applicants(applicants, companies)
        print(f"{len(applicants)} distinct applicants; "
              f"{len(resolved)} resolve to a company we hold")

        # a reload replaces the lot. The Orange Book is republished monthly as a
        # whole file, so there is no incremental form of it to preserve.
        for model in (ApprovedProduct, ProductPatent, ProductExclusivity):
            db.query(model).delete()

        for p in files["products"]:
            db.add(ApprovedProduct(
                appl_no=p["Appl_No"], product_no=p["Product_No"],
                appl_type=p["Appl_Type"], ingredient=p["Ingredient"],
                trade_name=p["Trade_Name"], applicant=p["Applicant_Full_Name"],
                approval_date=_iso(p["Approval_Date"]),
                company_ticker=resolved.get(p["Applicant_Full_Name"])))

        for p in files["patent"]:
            db.add(ProductPatent(
                appl_no=p["Appl_No"], product_no=p["Product_No"],
                patent_no=p["Patent_No"],
                expire_date=_iso(p["Patent_Expire_Date_Text"]),
                drug_substance=_flag(p.get("Drug_Substance_Flag")),
                drug_product=_flag(p.get("Drug_Product_Flag")),
                use_code=(p.get("Patent_Use_Code") or "").strip() or None,
                delisted=_flag(p.get("Delist_Flag"))))

        for e in files["exclusivity"]:
            db.add(ProductExclusivity(
                appl_no=e["Appl_No"], product_no=e["Product_No"],
                code=e["Exclusivity_Code"],
                expire_date=_iso(e["Exclusivity_Date"])))

        db.commit()
        linked = sum(1 for p in files["products"]
                     if resolved.get(p["Applicant_Full_Name"]))
        print(f"\nwritten. {linked} of {len(files['products'])} products "
              f"attributed to a company in the universe")
        print(f"  {len({t for t in resolved.values()})} companies have at least one")
    finally:
        db.close()


if __name__ == "__main__":
    main()
