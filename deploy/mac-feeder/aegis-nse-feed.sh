#!/bin/sh
# Aegis NSE feeder (see docs/deployment.md, "Railway: NSE data feeder").
#
# NSE blocks cloud servers, so a machine it does not block (this Mac)
# downloads the official end-of-day files + corporate actions, packs a small
# bundle for the tracked stocks and pushes it into the Railway worker over
# `railway ssh` (the database stays private). The worker then runs the normal
# validated, versioned, audited ingest in offline mode.
#
#   aegis-nse-feed.sh              # daily: the last 14 days (idempotent)
#   aegis-nse-feed.sh 2021-09-27   # backfill from a date
set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${AEGIS_FEEDER_PYTHON:-$REPO/../.venv/bin/python}"
CACHE="${AEGIS_FEEDER_CACHE:-$HOME/Library/Caches/aegis-nse}"
SERVICE="${AEGIS_FEEDER_SERVICE:-worker}"
SINCE="${1:-$(date -v-14d +%Y-%m-%d)}"
REMOTE=/tmp/aegis-feed
BUNDLE="$(mktemp -t aegis-bundle).tar.gz"
trap 'rm -f "$BUNDLE"' EXIT

echo "$(date '+%F %T') feeder: since $SINCE"
cd "$REPO"   # the Railway project link is recorded for this folder
# Stocks added in the app (beyond NIFTY 50) get licensed data too. If the
# lookup fails, carry on with NIFTY 50 rather than skip the evening.
TRACKED="$(railway ssh --service "$SERVICE" -- python -m app.cli list-nse 2>/dev/null | tr -d '\r' \
  | grep -E '^[A-Z0-9&_-]+$' | sed "s/^\(.*\)\$/'\1.NS'/" | tr '\n' ' ' || true)"   # quoted: M&M
echo "tracked in the app: $(echo "$TRACKED" | wc -w | tr -d ' ') NSE stocks"
# prefetch needs no database; settings still validate, so give inert values
AEGIS_ENV=development \
DATABASE_URL=postgresql+psycopg://unused@127.0.0.1:1/unused \
AEGIS_JWT_SECRET="feeder-$(openssl rand -hex 24)" \
  sh -c "cd '$REPO/backend' && '$PY' -m app.cli prefetch-nse --nifty50 $TRACKED --since '$SINCE' --dir '$CACHE' --bundle '$BUNDLE'"

railway ssh --service "$SERVICE" -- sh -c "rm -rf $REMOTE && mkdir -p $REMOTE && tar xz -C $REMOTE" < "$BUNDLE"
railway ssh --service "$SERVICE" -- python -m app.cli ingest-nse --nifty50 --offline --dir "$REMOTE" --since "$SINCE"
echo "$(date '+%F %T') feeder: done"
