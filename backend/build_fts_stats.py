"""
Measure how common each word is in the filing corpus, so the lexical half of
hybrid retrieval can ignore the words that carry no information.

The naive lexical query is the reason this file exists. Asking Postgres for
passages matching any word of a real question — "what risks does Bionano
Genomics face regarding its internal controls" — matches 294,793 of the 334,624
passages and takes 48 seconds to rank, because almost every annual report
contains "risk", "financial" and "reporting". ANDing the words instead matches
nothing, because no single passage contains all of them.

Neither failure is about the index. Both are about asking the words to do a job
the vectors already do well. Dense retrieval is good at subject matter; the
lexical side is only worth running for what the vectors are bad at, which is
rare exact tokens — a company name, a drug name, an NCT id, an accession. So
the search keeps the query's RAREST words and drops the rest, and rarity has to
be measured against this corpus rather than guessed: "clinical" and "patent" are
distinctive in English and ordinary here.

A 2% sample is enough. Document frequency at three decimal places does not move
between a 2% sample and a full count, and the full count is a scan of 3.6 GB.

    python build_fts_stats.py        # writes app/fts_stats.json, takes ~2 seconds
"""

import json
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from sqlalchemy import text

from app.database import engine
from app.semantic import FTS_CONFIG

OUT = os.path.join(os.path.dirname(__file__), "app", "fts_stats.json")

# percent of passages to sample. ts_stat has to build a tsvector for every row
# it sees, so this is the whole cost of the file.
SAMPLE_PCT = 2

# how many of the commonest lexemes to keep. Everything below this is rare
# enough that its exact frequency does not change any decision — the search
# treats an unlisted word as rare, which is what it is.
KEEP = 5000


def main():
    if engine.dialect.name != "postgresql":
        sys.exit("ts_stat is a Postgres function; nothing to build on SQLite.")

    with engine.connect() as conn:
        docs = conn.execute(text(
            f"select count(*) from filing_chunks tablesample system ({SAMPLE_PCT})"
        )).scalar()
        rows = conn.execute(text(f"""
            select word, ndoc from ts_stat(
              $$select to_tsvector('{FTS_CONFIG}', text)
                from filing_chunks tablesample system ({SAMPLE_PCT})$$)
            order by ndoc desc limit {KEEP}
        """)).all()

    df = {w: n for w, n in rows}
    payload = {"sample_docs": int(docs), "config": FTS_CONFIG, "df": df}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)

    print(f"sampled {docs:,} passages, kept {len(df):,} lexemes -> {OUT}")
    print("\ncommonest (these are the ones the lexical search will ignore):")
    for w, n in rows[:10]:
        print(f"  {w:<14} {n/docs:6.1%}")
    print("\nrarest kept (still listed, so still measurable):")
    for w, n in rows[-5:]:
        print(f"  {w:<14} {n/docs:6.2%}")


if __name__ == "__main__":
    main()
