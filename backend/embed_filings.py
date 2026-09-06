"""
This reads the narrative half of each company's annual report and embeds it, so
the chat can answer what a company says its biggest risks are rather than only
counting things. It fetches the latest 10-K or 20-F, pulls out the Risk Factors
and Management's Discussion sections, splits them into chunks and embeds each
one. It records what it extracted and not just what it stored, because a filing
that yields no risk factors is a normal outcome and looks identical to a filing
that was never read, so every attempt writes a Filing row saying which sections
were found; without that a gap in the coverage reads as a fact about the
company. It resumes, skipping a company whose filing is already stored, so an
interrupted run picks up where it left off and costs nothing to re-run. Run it
after ingest.py, with python embed_filings.py.
"""

import argparse
import os
import sys
import time

import numpy as np
from sqlalchemy import func

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from app.database import SessionLocal, init_db
from app.models import Company, Filing, FilingChunk
from app.filings import (latest_annual_filing, annual_filings, fetch_filing_text,
                         extract_sections, chunk_text)

EMBED_MODEL = "text-embedding-3-small"

# how many chunks go in one embedding request. the filings are long, so this is
# smaller than the trial batches to keep each request well inside the token limit.
BATCH = 64

# a polite pause between companies. each one is a couple of megabytes from
# EDGAR, which is a heavier ask than the JSON endpoints.
PAUSE = 0.5


# errors worth trying again. a rate limit is the expected one, but a request that
# times out or drops is just as temporary, and treating it as fatal ended a run
# 437 filings in with everything after it left unread.
TRANSIENT = ("rate", "timeout", "timed out", "connection", "temporarily",
             "502", "503", "504")


def embed(client, texts):
    """Embed a batch, retrying while the failure looks temporary."""
    for attempt in range(6):
        try:
            return client.embeddings.create(model=EMBED_MODEL, input=texts)
        except Exception as e:
            message = str(e).lower()
            if attempt == 5 or not any(t in message for t in TRANSIENT):
                raise
            time.sleep(5 * (attempt + 1))


def store_filing(db, company, meta, text, sections):
    """
    Write the filing record and its chunks. Returns the chunk rows to embed.

    Replaces whatever this company already had, so a refresh run swaps one
    company at a time and the table is never missing a filing it used to hold.
    """
    # Keyed on the accession, not the company. Deleting every filing a company
    # has was right when it had exactly one; with a history it would throw away
    # the four other years each time a fifth was written, and the run would end
    # with one filing per company again and no error to say why.
    old = db.query(Filing).filter(Filing.accession == meta["accession"],
                                  Filing.company_ticker == company.ticker).all()
    if old:
        ids = [f.id for f in old]
        db.query(FilingChunk).filter(FilingChunk.filing_id.in_(ids)).delete(
            synchronize_session=False)
        db.query(Filing).filter(Filing.id.in_(ids)).delete(
            synchronize_session=False)
        db.flush()

    filing = Filing(
        company_ticker=company.ticker, form=meta["form"], filed=meta["filed"],
        accession=meta["accession"], document=meta["document"],
        period_end=meta.get("period_end"), fiscal_year=meta.get("fiscal_year"),
        text_chars=len(text),
        # empty string means the filing was read and yielded nothing, which is
        # different from never having been read
        sections_found=",".join(sorted(sections)),
        risk_factors_chars=len(sections.get("risk_factors", "")),
        mdna_chars=len(sections.get("mdna", "")),
    )
    db.add(filing)
    db.flush()

    chunks = []
    for name, body in sorted(sections.items()):
        for i, piece in enumerate(chunk_text(body)):
            chunk = FilingChunk(filing_id=filing.id, section=name, ordinal=i,
                                text=piece)
            db.add(chunk)
            chunks.append(chunk)
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="re-read every filing, replacing what is stored")
    ap.add_argument("--missing-section", metavar="NAME",
                    help="re-read only filings that yielded no NAME section")
    ap.add_argument("--tickers", metavar="LIST",
                    help="re-read only these companies, comma separated")
    ap.add_argument("--history", type=int, metavar="N", default=1,
                    help="read the N most recent annual reports per company "
                         "rather than only the latest (default 1)")
    ap.add_argument("--oversized-section", metavar="NAME:CHARS",
                    help="re-read filings whose NAME section exceeds CHARS, "
                         "which is how a bad boundary shows itself")
    ap.add_argument("--stamp-periods", action="store_true",
                    help="fill in period_end and fiscal_year for filings stored "
                         "before those were recorded, without re-reading them")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()

    # The filings read before the history existed carry no period, so a question
    # naming a year cannot reach the most recent report of all. Stamping them
    # needs the submissions feed and not the documents: one request per company
    # against three thousand multi-megabyte fetches to learn the same thing.
    if args.stamp_periods:
        rows = db.query(Filing).filter(Filing.fiscal_year.is_(None)).all()
        by_ticker = {}
        for f in rows:
            by_ticker.setdefault(f.company_ticker, []).append(f)
        print(f"Stamping {len(rows)} filings across {len(by_ticker)} companies...\n")
        stamped = missing = 0
        for n, (ticker, filings_) in enumerate(sorted(by_ticker.items()), 1):
            company = db.get(Company, ticker)
            if company is None or not company.cik:
                continue
            try:
                known = {m["accession"]: m for m in annual_filings(company.cik, 12)}
            except Exception as e:
                print(f"  [{n:>3}] {ticker:6} FAILED: {e}")
                continue
            for f in filings_:
                meta = known.get(f.accession)
                if meta is None:
                    # the filing is stored but no longer among the recent ones,
                    # which is a fact worth seeing rather than a silent skip
                    missing += 1
                    continue
                f.period_end = meta["period_end"]
                f.fiscal_year = meta["fiscal_year"]
                stamped += 1
            db.commit()
            time.sleep(0.05)
        db.close()
        print(f"\nDONE. {stamped} stamped, {missing} not found in the "
              f"submissions feed.")
        return

    # already done, so a re-run costs nothing
    done = {t for (t,) in db.query(Filing.company_ticker).all()}
    # --refresh re-reads everything. Needed when the sections themselves change:
    # the intellectual property section was added after most filings had been
    # chunked, so 29 of 776 have it and the rest were read before it existed.
    #
    # Replacement happens per company, inside the loop, rather than by emptying
    # the tables first. A wipe would leave the chat with no filing text at all
    # for however long the run takes, and would lose everything if the run died
    # halfway, which is exactly what happened to the first alias crawl.
    # Re-read only what is missing a section, rather than everything. A rule
    # change usually affects one section, and the filings that already yield it
    # would be fetched and embedded again to arrive at the same rows. Widening
    # the intellectual-property bounds recovers about one miss in five, which is
    # worth 274 fetches and is not worth 787.
    # A section that is too large is as wrong as one that is missing, and it
    # does not show up as a gap. A management discussion running to 500,000
    # characters is the whole filing: the heading matched the table of contents
    # and the section ran from there to the next real heading. Those filings
    # already have every section, so --missing-section will never revisit them.
    if args.tickers or args.oversized_section:
        wanted = set()
        if args.tickers:
            wanted |= {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        if args.oversized_section:
            name, _, size = args.oversized_section.partition(":")
            column = {"mdna": Filing.mdna_chars,
                      "risk_factors": Filing.risk_factors_chars}[name]
            wanted |= {t for (t,) in db.query(Filing.company_ticker)
                         .filter(column > int(size)).all()}
        companies = [c for c in db.query(Company).order_by(Company.ticker).all()
                     if c.cik and c.ticker in wanted]
    elif args.missing_section:
        have = {t for (t,) in db.query(Filing.company_ticker)
                  .join(FilingChunk, FilingChunk.filing_id == Filing.id)
                  .filter(FilingChunk.section == args.missing_section).distinct()}
        companies = [c for c in db.query(Company).order_by(Company.ticker).all()
                     if c.cik and c.ticker not in have]
    else:
        # "Already stored" means a company has as many years as was asked for,
        # not that it has any at all. With --history 5 the default test skipped
        # every company in the database, because each had the one filing it was
        # given before the history existed, and the run reported success having
        # read eleven.
        counts = dict(db.query(Filing.company_ticker, func.count(Filing.id))
                        .group_by(Filing.company_ticker).all())
        companies = [c for c in db.query(Company).order_by(Company.ticker).all()
                     if c.cik and (args.refresh
                                   or counts.get(c.ticker, 0) < args.history)]
    if not companies:
        print("Every company already has a filing stored. Nothing to do.")
        db.close()
        return

    from openai import OpenAI
    client = OpenAI()

    print(f"Reading filings for {len(companies)} companies "
          f"({len(done)} already stored)...\n")

    for n, company in enumerate(companies, 1):
        try:
            metas = (annual_filings(company.cik, args.history)
                     if args.history > 1 else
                     [m for m in [latest_annual_filing(company.cik)] if m])
            if not metas:
                print(f"  [{n:>3}/{len(companies)}] {company.ticker:6} "
                      f"no annual filing on EDGAR")
                continue
        except Exception as e:
            print(f"  [{n:>3}/{len(companies)}] {company.ticker:6} FAILED: {e}")
            continue

        # already stored, so a resumed history run pays only for what is left
        have = {a for (a,) in db.query(Filing.accession)
                  .filter(Filing.company_ticker == company.ticker).all()}
        if not args.refresh and not args.missing_section:
            metas = [m for m in metas if m["accession"] not in have]
        if not metas:
            continue

        for meta in metas:
            try:
                # the form decides how the filing is read, not just how it is
                # parsed: a 40-F keeps its narrative in exhibits, so fetching the
                # primary document alone returns a few pages of certifications
                text = fetch_filing_text(company.cik, meta["accession"],
                                         meta["document"], meta["form"])
                sections = extract_sections(text, meta['form'])
            except Exception as e:
                # a failed fetch is not recorded, so the next run tries again
                # rather than treating this filing as read and empty. One bad
                # year does not cost the other four.
                print(f"  [{n:>3}/{len(companies)}] {company.ticker:6} "
                      f"FY{meta.get('fiscal_year', '?')} FAILED: {e}")
                continue

            chunks = store_filing(db, company, meta, text, sections)

            # embed in batches, committing as it goes so an interruption keeps
            # what it has already paid for
            for i in range(0, len(chunks), BATCH):
                batch = chunks[i:i + BATCH]
                resp = embed(client, [c.text for c in batch])
                for chunk, item in zip(batch, resp.data):
                    chunk.embedding = np.asarray(item.embedding, dtype=np.float32)
                db.commit()

            db.commit()
            found = ", ".join(f"{k}={len(v) // 1000}k"
                              for k, v in sorted(sections.items()))
            print(f"  [{n:>3}/{len(companies)}] {company.ticker:6} "
                  f"FY{meta.get('fiscal_year', '?')} {meta['form']:5} "
                  f"{meta['filed']}  {found or 'no sections found':30} "
                  f"chunks={len(chunks)}")
            time.sleep(PAUSE)

    total = db.query(FilingChunk).count()
    without = db.query(Filing).filter(
        ~Filing.sections_found.contains("risk_factors")).count()
    db.close()
    print(f"\nDONE. {total} chunks stored. "
          f"{without} filings yielded no risk factors, which is worth checking "
          f"rather than assuming.")


if __name__ == "__main__":
    main()
