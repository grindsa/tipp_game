#!/usr/bin/env sh
set -eu

# Restore utility for archives created by scripts/backup.sh.
# This script restores DB dump, host files archive, and media volume.

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose --project-directory $PROJECT_DIR}"
TMP_ROOT="${TMP_ROOT:-${TMPDIR:-/tmp}}"
RESTORE_CONFIRM="${RESTORE_CONFIRM:-no}"
RESTORE_CLEAR_MEDIA="${RESTORE_CLEAR_MEDIA:-yes}"

usage() {
  echo "Usage: $0 /path/to/tipp_game-backup-YYYYmmdd-HHMMSS.tar.gz"
  echo "Set RESTORE_CONFIRM=yes to run a destructive restore."
}

if [ "${1:-}" = "" ]; then
  usage
  exit 1
fi

archive_path="$1"

if [ ! -f "$archive_path" ]; then
  echo "ERROR: archive not found: $archive_path" >&2
  exit 1
fi

if [ "$RESTORE_CONFIRM" != "yes" ]; then
  echo "ERROR: restore is destructive. Re-run with RESTORE_CONFIRM=yes" >&2
  exit 1
fi

if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo "ERROR: missing $PROJECT_DIR/.env" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a
. "$PROJECT_DIR/.env"
set +a

if [ -z "${MARIADB_ROOT_PASSWORD:-}" ]; then
  echo "ERROR: MARIADB_ROOT_PASSWORD must be set in .env" >&2
  exit 1
fi

work_dir="$TMP_ROOT/restore-$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$work_dir"
trap 'rm -rf "$work_dir"' EXIT INT TERM

cd "$PROJECT_DIR"

echo "Extracting archive to $work_dir"
tar -xzf "$archive_path" -C "$work_dir"

for required in db.sql.gz files.tar.gz media.tar manifest.sha256; do
  if [ ! -f "$work_dir/$required" ]; then
    echo "ERROR: missing $required in backup archive" >&2
    exit 1
  fi
done

echo "Validating checksum manifest"
(
  cd "$work_dir"
  sha256sum -c manifest.sha256
)

echo "Restoring database dump"
gunzip -c "$work_dir/db.sql.gz" | $COMPOSE_CMD exec -T db sh -lc "mariadb -uroot -p\"$MARIADB_ROOT_PASSWORD\""

echo "Restoring host filesystem archive"
tar -xzf "$work_dir/files.tar.gz" -C /

echo "Restoring media volume"
if [ "$RESTORE_CLEAR_MEDIA" = "yes" ]; then
  $COMPOSE_CMD run --rm --no-deps -v "$work_dir:/restore" web sh -lc 'rm -rf /app/media/* && cd /app/media && tar -xf /restore/media.tar'
else
  $COMPOSE_CMD run --rm --no-deps -v "$work_dir:/restore" web sh -lc 'cd /app/media && tar -xf /restore/media.tar'
fi

echo "Restore completed successfully."
