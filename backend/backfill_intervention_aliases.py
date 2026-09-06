"""
This fetches the registry's statement that two intervention names are the same
thing. trials.interventions records what a study tested, but a candidate is
filed under more than one name, ivacaftor being entered as "IVA", "Ivacaftor"
and "VX-770" across Vertex's trials, so grouping by the string alone counts one
drug three times. ClinicalTrials.gov states the equivalence in otherNames on
each intervention, and that field was never stored, not even inside the embedded
summary which took only the name, so unlike backfill_interventions.py this one
cannot read what we already hold and has to ask. It asks cheaply, requesting
studies by id a hundred at a time with only the two modules needed, so covering
the corpus is a few hundred small requests instead of a re-ingest. Aliases are
stored exactly as filed, since a sponsor often crams several into one string
like "VX-770, IVA" and tidying that here would lose what the registry actually
said. Run it with python backfill_intervention_aliases.py, with --dry-run to
report without writing or --limit N for a short run.
"""
import argparse
import json
import time

import requests
from sqlalchemy import inspect, text

from app.database import SessionLocal, engine, init_db
from app.models import Trial

CT_STUDIES = "https://clinicaltrials.gov/api/v2/studies"
FIELDS = ("protocolSection.identificationModule.nctId,"
          "protocolSection.armsInterventionsModule")
BATCH = 100
# the registry asks for a contact in the agent, the same courtesy the SEC does
UA = {"User-Agent": "Readbase/1.0"}


def ensure_column():
    cols = {c["name"] for c in inspect(engine).get_columns("trials")}
    if "intervention_aliases" in cols:
        return False
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE trials ADD COLUMN intervention_aliases TEXT"))
    return True


def fetch(nct_ids):
    """{nct_id: {name: [other names]}} for one batch, as filed."""
    resp = requests.get(CT_STUDIES, headers=UA, timeout=60, params={
        "filter.ids": ",".join(nct_ids),
        "fields": FIELDS,
        "pageSize": len(nct_ids) * 2,
    })
    resp.raise_for_status()
    out = {}
    for study in resp.json().get("studies", []):
        ps = study.get("protocolSection", {})
        nct = ps.get("identificationModule", {}).get("nctId")
        if not nct:
            continue
        aliases = {
            i["name"].strip(): i["otherNames"]
            for i in (ps.get("armsInterventionsModule", {}).get("interventions") or [])
            if i.get("name") and i.get("otherNames")
        }
        out[nct] = aliases
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    init_db()
    if ensure_column():
        print("added trials.intervention_aliases")

    db = SessionLocal()
    rows = db.query(Trial).filter(Trial.intervention_aliases.is_(None)).all()
    by_nct = {}
    for t in rows:
        if t.nct_id:
            by_nct.setdefault(t.nct_id, []).append(t)
    ids = sorted(by_nct)
    if args.limit:
        ids = ids[:args.limit]
    print(f"{len(ids)} studies to ask about, {len(rows)} trial rows behind them\n")

    stated = silent = failed = 0
    for start in range(0, len(ids), BATCH):
        batch = ids[start:start + BATCH]
        try:
            found = fetch(batch)
        except Exception as e:
            failed += len(batch)
            print(f"  [{start + len(batch):>6}/{len(ids)}] batch FAILED: {e}")
            continue
        for nct in batch:
            aliases = found.get(nct)
            for trial in by_nct[nct]:
                if aliases:
                    trial.intervention_aliases = json.dumps(aliases)
                else:
                    # asked and told nothing: an empty object records that we
                    # looked, so a later run does not ask again
                    trial.intervention_aliases = "{}"
            if aliases:
                stated += 1
            else:
                silent += 1
        if not args.dry_run:
            db.commit()
        if (start // BATCH) % 20 == 0:
            print(f"  [{min(start + BATCH, len(ids)):>6}/{len(ids)}] "
                  f"{stated} with aliases, {silent} without")
        time.sleep(0.25)

    if args.dry_run:
        db.rollback()
    db.close()
    verb = "would record" if args.dry_run else "recorded"
    print(f"\nDONE. {verb} aliases for {stated} studies; {silent} state none; "
          f"{failed} could not be fetched.")
    print("A study stating none is not a study whose drug has one name — it is "
          "a sponsor who did not fill the field in.")


if __name__ == "__main__":
    main()
