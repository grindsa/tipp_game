#!/usr/bin/env sh
set -eu

# Manual backup wrapper using the same knobs as scripts/backup.cron.example.
# Customize values below for your environment, then run:
#   ./scripts/backup.manual.sh
# Values can be set in .env (preferred) or exported before execution.

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)}"

cd "$PROJECT_DIR"

PROJECT_DIR="$PROJECT_DIR" ./scripts/backup.sh "$@"
