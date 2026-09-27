#!/bin/sh
# Install (or refresh) the Aegis NSE feeder as a macOS LaunchAgent.
#
# macOS does not let background jobs read ~/Documents, ~/Desktop or
# ~/Downloads, so the feeder runs from its own copy of the code in
# ~/Library/Application Support/aegis-feeder (with its own virtualenv and
# Railway project link). Re-run this after changing the code.
#
#   deploy/mac-feeder/install-feeder.sh <railway-project-id>
set -eu

PROJECT="${1:?usage: install-feeder.sh <railway-project-id>}"
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$HOME/Library/Application Support/aegis-feeder"
PYTHON="${AEGIS_FEEDER_BASE_PYTHON:-/opt/homebrew/bin/python3.11}"
PLIST="$HOME/Library/LaunchAgents/com.aegis.nse-feed.plist"

mkdir -p "$DEST/repo/deploy"
rsync -a --delete --exclude __pycache__ --exclude '*.egg-info' \
  "$SRC/backend/app" "$SRC/backend/pyproject.toml" "$DEST/repo/backend/"
rsync -a --delete "$SRC/config/" "$DEST/repo/config/"
rsync -a --delete "$SRC/deploy/mac-feeder/" "$DEST/repo/deploy/mac-feeder/"

[ -x "$DEST/.venv/bin/python" ] || "$PYTHON" -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install -q --upgrade pip
"$DEST/.venv/bin/pip" install -q "$DEST/repo/backend"

(cd "$DEST/repo" && railway link --project "$PROJECT" --environment production --service worker >/dev/null)

[ -f "$PLIST" ] && launchctl unload "$PLIST" 2>/dev/null || true
sed -e "s#REPO_PATH#$DEST/repo#" -e "s#LOG_PATH#$HOME/Library/Logs/aegis-nse-feed.log#" \
  "$SRC/deploy/mac-feeder/com.aegis.nse-feed.plist" > "$PLIST"
plutil -lint "$PLIST" >/dev/null
launchctl load "$PLIST"
echo "feeder installed in $DEST; runs 19:10 IST Mon-Fri; log: ~/Library/Logs/aegis-nse-feed.log"
