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


def embed(client, texts):
    """Embed a batch, retrying on the tokens-per-minute rate limit."""
    for attempt in range(6):
        try:
            return client.embeddings.create(model=EMBED_MODEL, input=texts)
        except Exception as e:
            if "rate" not in str(e).lower() or attempt == 5:
                raise
            time.sleep(5 * (attempt + 1))


def store_filing(db, company, meta, text, sections):
    """Write the filing record and its chunks. Returns the chunk rows to embed."""
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
    init_db()
    db = SessionLocal()

    # already done, so a re-run costs nothing
    done = {t for (t,) in db.query(Filing.company_ticker).all()}
    companies = [c for c in db.query(Company).order_by(Company.ticker).all()
                 if c.ticker not in done and c.cik]
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
            text = fetch_filing_text(company.cik, meta["accession"],
                                     meta["document"])
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
