#!/usr/bin/env bash
#
# Take a snapshot of what the APIs currently return, without touching the
# database. Meant to run unattended on a schedule; see snapshot.plist.
#
# Weekly, not daily. About 1% of the trials in this universe start in any given
# month, so a daily run spends 1,574 API requests to capture almost nothing and
# fills the archive with dates that differ from each other by rounding.
#
# The point of running it at all is that "what changed" needs two snapshots
# taken by the same code at different times, and nothing else produces that.
#
#   ./snapshot.sh          take one if today has none
#   ./snapshot.sh --force  take one regardless
#
set -euo pipefail

cd "$(dirname "$0")"
LOG_DIR="${SNAPSHOT_LOG_DIR:-$PWD/logs}"
mkdir -p "$LOG_DIR"
TODAY="$(date -u +%Y-%m-%d)"
LOG="$LOG_DIR/snapshot-$TODAY.log"

# Read the values rather than sourcing the file: SEC_USER_AGENT contains a
# space, and passing it through an xargs pipeline truncates it to the first
# word. SEC then rejects every request with a 403 while the run exits 0.
env_value() {
  sed -n "s/^$1=//p" backend/.env | head -1 | sed 's/^"//;s/"$//'
}
SEC_UA="$(env_value SEC_USER_AGENT)"

if [ ${#SEC_UA} -lt 10 ]; then
  echo "SEC_USER_AGENT is missing or too short (${#SEC_UA} chars)." >&2
  echo "SEC rejects unidentified automated requests, so this would 403 silently." >&2
  exit 1
fi

# Don't take a second snapshot of the same day. Two snapshots hours apart are
# not a period of time, and the later one would replace the earlier under the
# same date anyway.
if [ "${1:-}" != "--force" ]; then
  if docker compose run --rm --entrypoint python ingest -c "
from app.raw_store import get_store, manifest_key
import sys
try:
    get_store().get(manifest_key('$TODAY'))
    sys.exit(0)
except Exception:
    sys.exit(1)
" >/dev/null 2>&1; then
    echo "$TODAY already has a snapshot. Use --force to take another."
    exit 0
  fi
fi

echo "=== snapshot $TODAY started $(date -u +%H:%M:%SZ)" | tee -a "$LOG"

# --snapshot-only archives what the APIs returned without writing to the
# database, so a scheduled run can never disturb what the app is serving.
if docker compose run --rm --build \
     -e SEC_USER_AGENT="$SEC_UA" \
     ingest python -u ingest.py --snapshot-only >>"$LOG" 2>&1; then
  taken=$(grep -c '^  \[' "$LOG" || true)
  failed=$(grep -c FAILED "$LOG" || true)
  echo "=== snapshot $TODAY done: $taken companies, $failed failed" | tee -a "$LOG"
  # A run that exits 0 having fetched almost nothing is the failure this whole
  # project keeps meeting: silent, and shaped like success.
  if [ "$taken" -lt 700 ]; then
    echo "Only $taken companies were archived, out of about 787." >&2
    echo "That is a partial snapshot; see $LOG." >&2
    exit 1
  fi
else
  echo "=== snapshot $TODAY FAILED, see $LOG" | tee -a "$LOG" >&2
  exit 1
fi
