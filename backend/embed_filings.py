"""
This script reads the narrative half of each company's annual report and embeds
it, so the chat can answer "what does this company say are its biggest risks?"
rather than only counting things. It fetches the latest 10-K or 20-F, pulls out
the Risk Factors and Management's Discussion sections, splits them into chunks
and embeds each one. Run it after ingest.py, with python embed_filings.py.

It records what it extracted, not just what it stored. A filing that yields no
risk factors is a normal outcome, and one that looks identical to a filing that
was never read, so every attempt writes a Filing row saying which sections were
found. Without that a gap in the coverage reads as a fact about the company.

It resumes: a company whose filing is already stored is skipped, so an
interrupted run picks up where it left off and costs nothing to re-run.
"""

import argparse
import os
import sys
import time

import numpy as np

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from app.database import SessionLocal, init_db
from app.models import Company, Filing, FilingChunk
from app.filings import (latest_annual_filing, fetch_filing_text,
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
    old = db.query(Filing).filter(Filing.company_ticker == company.ticker).all()
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
    args = ap.parse_args()

    init_db()
    db = SessionLocal()

    # already done, so a re-run costs nothing
    done = {t for (t,) in db.query(Filing.company_ticker).all()}
    # --refresh re-reads everything. Needed when the sections themselves change:
    # the intellectual property section was added after most filings had been
    # chunked, so 29 of 776 have it and the rest were read before it existed.
    #
    # Replacement happens per company, inside the loop, rather than by emptying
    # the tables first. A wipe would leave the chat with no filing text at all
    # for however long the run takes, and would lose everything if the run died
    # halfway — which is exactly what happened to the first alias crawl.
    companies = [c for c in db.query(Company).order_by(Company.ticker).all()
                 if c.cik and (args.refresh or c.ticker not in done)]
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
            meta = latest_annual_filing(company.cik)
            if meta is None:
                print(f"  [{n:>3}/{len(companies)}] {company.ticker:6} "
                      f"no annual filing on EDGAR")
                continue
            # the form decides how the filing is read, not just how it is
            # parsed: a 40-F keeps its narrative in exhibits, so fetching the
            # primary document alone returns a few pages of certifications
            text = fetch_filing_text(company.cik, meta["accession"],
                                     meta["document"], meta["form"])
            sections = extract_sections(text, meta['form'])
        except Exception as e:
            # a failed fetch is not recorded, so the next run tries again rather
            # than treating this company as read and empty
            print(f"  [{n:>3}/{len(companies)}] {company.ticker:6} FAILED: {e}")
            continue

        chunks = store_filing(db, company, meta, text, sections)

        # embed in batches, committing as it goes so an interruption keeps what
        # it has already paid for
        for i in range(0, len(chunks), BATCH):
            batch = chunks[i:i + BATCH]
            resp = embed(client, [c.text for c in batch])
            for chunk, item in zip(batch, resp.data):
                chunk.embedding = np.asarray(item.embedding, dtype=np.float32)
            db.commit()

        db.commit()
        found = ", ".join(f"{k}={len(v) // 1000}k" for k, v in sorted(sections.items()))
        print(f"  [{n:>3}/{len(companies)}] {company.ticker:6} "
              f"{meta['form']:5} {meta['filed']}  "
              f"{found or 'no sections found':30} chunks={len(chunks)}")
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
