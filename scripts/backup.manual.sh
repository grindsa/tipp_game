#!/usr/bin/env sh
set -eu

# Manual backup wrapper using the same knobs as scripts/backup.cron.example.
# Customize values below for your environment, then run:
#   ./scripts/backup.manual.sh
# Values can be set in .env (preferred) or exported before execution.

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)}"

if [ -f "$PROJECT_DIR/.env" ]; then
	# shellcheck disable=SC1091
	set -a
	. "$PROJECT_DIR/.env"
	set +a
fi

# Remote backup target
REMOTE_TARGET="${REMOTE_TARGET:-}"
REMOTE_DIR="${REMOTE_DIR:-/srv/backups/tipp_game}"
SSH_KEY="${SSH_KEY:-}"

# Optional WhatsApp destination. Empty disables notifications.
WA_NOTIFY_NUMBER="${WA_NOTIFY_NUMBER:-}"

# Retention
LOCAL_KEEP="${LOCAL_KEEP:-3}"
REMOTE_KEEP="${REMOTE_KEEP:-12}"

cd "$PROJECT_DIR"

PROJECT_DIR="$PROJECT_DIR" \
REMOTE_TARGET="$REMOTE_TARGET" \
REMOTE_DIR="$REMOTE_DIR" \
SSH_KEY="$SSH_KEY" \
WA_NOTIFY_NUMBER="$WA_NOTIFY_NUMBER" \
LOCAL_KEEP="$LOCAL_KEEP" \
REMOTE_KEEP="$REMOTE_KEEP" \
./scripts/backup.sh
