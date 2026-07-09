#!/usr/bin/env sh
set -eu

# Biweekly backup for the tipp_game stack.
# Includes DB dump, persistent host files, media volume, checksums, optional SCP upload, and retention.

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose --project-directory $PROJECT_DIR}"
APP_NAME="${APP_NAME:-tipp_game}"
BACKUP_ROOT="${BACKUP_ROOT:-${TMPDIR:-/tmp}/tipp_game-backups}"
TMP_ROOT="${TMP_ROOT:-${TMPDIR:-/tmp}}"
LOCAL_KEEP="${LOCAL_KEEP:-}"
REMOTE_KEEP="${REMOTE_KEEP:-}"
REMOTE_TARGET="${REMOTE_TARGET:-}"    # user@host
REMOTE_DIR="${REMOTE_DIR:-}"
SSH_KEY="${SSH_KEY:-}"                # optional private key path for ssh/scp
WA_NOTIFY_NUMBER="${WA_NOTIFY_NUMBER:-}"
WA_NOTIFY_SRV="${WA_NOTIFY_SRV:-}"
WA_NOTIFY_PORT="${WA_NOTIFY_PORT:-}"
LOG_FILE="${LOG_FILE:-$PROJECT_DIR/logs/backup.log}"
CHECK_CONFIG=0

# host paths
STATIC_DIR="${STATIC_DIR:-/srv/data/tipp_game/static}"
LOGS_DIR="${LOGS_DIR:-/srv/data/tipp_game/logs}"
WALLABAG_IMG_DIR="${WALLABAG_IMG_DIR:-/srv/data/tipp_game/wallabag/images}"
CRON_DIR="${CRON_DIR:-/srv/data/tipp_game/cron}"

now_utc="$(date -u +%Y%m%d-%H%M%S)"
run_id="${APP_NAME}-backup-${now_utc}"
work_dir="$TMP_ROOT/$run_id"
out_dir="$BACKUP_ROOT"
final_archive="$out_dir/${run_id}.tar.gz"

if [ "${1:-}" = "--check-config" ]; then
  CHECK_CONFIG=1
  shift
fi

if [ "$#" -ne 0 ]; then
  echo "Usage: $0 [--check-config]" >&2
  exit 1
fi

log() {
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '%s %s\n' "$ts" "$*" | tee -a "$LOG_FILE"
}

# Parse one value from .env without executing the file.
read_env_value() {
  key="$1"
  file="$2"
  awk -v k="$key" '
    {
      line=$0
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
      if (line == "" || line ~ /^#/) next

      if (line ~ "^" k "[[:space:]]*=") {
        sub("^" k "[[:space:]]*=[[:space:]]*", "", line)
      } else if (line ~ "^" k "[[:space:]]*:") {
        sub("^" k "[[:space:]]*:[[:space:]]*", "", line)
      } else {
        next
      }

      gsub(/^["\047]|["\047]$/, "", line)
      print line
      exit
    }
  ' "$file"
}

notify_backup_result() {
  exit_code="$1"

  if [ -z "$WA_NOTIFY_NUMBER" ]; then
    return 0
  fi

  if [ -z "$WA_NOTIFY_SRV" ] || [ -z "$WA_NOTIFY_PORT" ]; then
    log "WARN: WA_NOTIFY_NUMBER set but WA_NOTIFY_SRV/WA_NOTIFY_PORT missing; skipping WA notification"
    return 0
  fi

  result="successful"
  if [ "$exit_code" -ne 0 ]; then
    result="failed"
  fi

  wa_msg="$(date +%d.%m.%Y) tipp_game backup ${result}. run_id:${run_id}"

  if WA_MSG="$wa_msg" WA_DEST="$WA_NOTIFY_NUMBER" WA_HOST="$WA_NOTIFY_SRV" WA_PORT_VAL="$WA_NOTIFY_PORT" \
    $COMPOSE_CMD run --rm --no-deps -e WA_MSG -e WA_DEST -e WA_HOST -e WA_PORT_VAL jobs \
      python -c 'import os; from game.wa_hack_cli import simple_send; simple_send(os.environ["WA_HOST"], os.environ["WA_PORT_VAL"], os.environ["WA_DEST"], os.environ["WA_MSG"])' >/dev/null 2>&1
  then
    log "WA notification sent to configured destination"
  else
    log "WARN: WA notification failed"
  fi
}

finalize() {
  exit_code="$1"
  if [ "$CHECK_CONFIG" -eq 0 ]; then
    notify_backup_result "$exit_code"
  fi
  rm -rf "$work_dir"
}
trap 'finalize $?' EXIT

cd "$PROJECT_DIR"

env_file="$PROJECT_DIR/.env"
if [ ! -f "$env_file" ]; then
  log "ERROR: missing $PROJECT_DIR/.env"
  exit 1
fi

if [ -z "${MARIADB_ROOT_PASSWORD:-}" ]; then
  MARIADB_ROOT_PASSWORD="$(read_env_value MARIADB_ROOT_PASSWORD "$env_file")"
fi
if [ -z "${MARIADB_DATABASE:-}" ]; then
  MARIADB_DATABASE="$(read_env_value MARIADB_DATABASE "$env_file")"
fi
if [ -z "${WB_DATABASE:-}" ]; then
  WB_DATABASE="$(read_env_value WB_DATABASE "$env_file")"
fi
if [ -z "${REMOTE_TARGET:-}" ]; then
  REMOTE_TARGET="$(read_env_value REMOTE_TARGET "$env_file")"
fi
if [ -z "${REMOTE_DIR:-}" ]; then
  REMOTE_DIR="$(read_env_value REMOTE_DIR "$env_file")"
fi
if [ -z "${SSH_KEY:-}" ]; then
  SSH_KEY="$(read_env_value SSH_KEY "$env_file")"
fi
if [ -z "${LOCAL_KEEP:-}" ]; then
  LOCAL_KEEP="$(read_env_value LOCAL_KEEP "$env_file")"
fi
if [ -z "${REMOTE_KEEP:-}" ]; then
  REMOTE_KEEP="$(read_env_value REMOTE_KEEP "$env_file")"
fi
if [ -z "${WA_ADMIN_NUMBER:-}" ]; then
  WA_ADMIN_NUMBER="$(read_env_value WA_ADMIN_NUMBER "$env_file")"
fi
if [ -z "${WA_SRV:-}" ]; then
  WA_SRV="$(read_env_value WA_SRV "$env_file")"
fi
if [ -z "${WA_PORT:-}" ]; then
  WA_PORT="$(read_env_value WA_PORT "$env_file")"
fi
if [ -z "${WA_NOTIFY_NUMBER:-}" ]; then
  WA_NOTIFY_NUMBER="$(read_env_value WA_NOTIFY_NUMBER "$env_file")"
fi
if [ -z "${WA_NOTIFY_SRV:-}" ]; then
  WA_NOTIFY_SRV="$(read_env_value WA_NOTIFY_SRV "$env_file")"
fi
if [ -z "${WA_NOTIFY_PORT:-}" ]; then
  WA_NOTIFY_PORT="$(read_env_value WA_NOTIFY_PORT "$env_file")"
fi

LOCAL_KEEP="${LOCAL_KEEP:-3}"
REMOTE_KEEP="${REMOTE_KEEP:-12}"
REMOTE_DIR="${REMOTE_DIR:-/volume1/public/Backups/web-srv/tipp_game}"
WA_NOTIFY_NUMBER="${WA_NOTIFY_NUMBER:-${WA_ADMIN_NUMBER:-}}"
WA_NOTIFY_SRV="${WA_NOTIFY_SRV:-${WA_SRV:-}}"
WA_NOTIFY_PORT="${WA_NOTIFY_PORT:-${WA_PORT:-}}"

REMOTE_DIR_NORM="${REMOTE_DIR%/}"
if [ -z "$REMOTE_DIR_NORM" ]; then
  REMOTE_DIR_NORM="/"
fi

if [ -z "${MARIADB_ROOT_PASSWORD:-}" ]; then
  log "ERROR: MARIADB_ROOT_PASSWORD must be set in .env"
  exit 1
fi

ssh_opts=""
if [ -n "$SSH_KEY" ]; then
  if [ ! -f "$SSH_KEY" ]; then
    log "ERROR: SSH_KEY file not found: $SSH_KEY"
    exit 1
  fi
  ssh_opts="-i $SSH_KEY"
fi

# Build DB list dynamically from env (primary + optional wallabag DB).
DB_LIST="${MARIADB_DATABASE:-}"
if [ -n "${WB_DATABASE:-}" ]; then
  DB_LIST="$DB_LIST ${WB_DATABASE}"
fi

if [ -z "$(printf '%s' "$DB_LIST" | tr -d ' ')" ]; then
  log "ERROR: no database names resolved from MARIADB_DATABASE/WB_DATABASE"
  exit 1
fi

if [ "$CHECK_CONFIG" -eq 1 ]; then
  if $COMPOSE_CMD ps -q db >/dev/null 2>&1; then
    db_service_status="ok"
  else
    db_service_status="not-found-or-unreachable"
  fi

  if [ -n "$REMOTE_TARGET" ]; then
    remote_upload="enabled"
  else
    remote_upload="disabled"
  fi

  if [ -n "$WA_NOTIFY_NUMBER" ]; then
    wa_notify="enabled"
  else
    wa_notify="disabled"
  fi

  echo "backup config check"
  echo "project_dir=$PROJECT_DIR"
  echo "compose_cmd=$COMPOSE_CMD"
  echo "env_file=$env_file"
  echo "app_name=$APP_NAME"
  echo "backup_root=$BACKUP_ROOT"
  echo "tmp_root=$TMP_ROOT"
  echo "local_keep=$LOCAL_KEEP"
  echo "remote_keep=$REMOTE_KEEP"
  echo "remote_target=${REMOTE_TARGET:-<empty>}"
  echo "remote_dir=$REMOTE_DIR_NORM"
  echo "ssh_key=${SSH_KEY:-<empty>}"
  echo "db_list=$DB_LIST"
  echo "wa_notify_number=${WA_NOTIFY_NUMBER:-<empty>}"
  echo "wa_notify_srv=${WA_NOTIFY_SRV:-<empty>}"
  echo "wa_notify_port=${WA_NOTIFY_PORT:-<empty>}"
  echo "static_dir=$STATIC_DIR"
  echo "logs_dir=$LOGS_DIR"
  echo "wallabag_img_dir=$WALLABAG_IMG_DIR"
  echo "cron_dir=$CRON_DIR"
  echo "remote_upload=$remote_upload"
  echo "wa_notification=$wa_notify"
  echo "db_service_status=$db_service_status"
  echo "result=ok"
  exit 0
fi

if ! $COMPOSE_CMD ps -q db >/dev/null 2>&1; then
  log "ERROR: compose service 'db' not found"
  exit 1
fi

mkdir -p "$out_dir" "$(dirname "$LOG_FILE")" "$work_dir"

db_sql="$work_dir/db.sql"
db_sql_gz="$work_dir/db.sql.gz"
files_tar="$work_dir/files.tar.gz"
media_tar="$work_dir/media.tar"
meta_txt="$work_dir/meta.txt"

log "Starting backup run $run_id"

log "Creating MariaDB dump"
# shellcheck disable=SC2086
$COMPOSE_CMD exec -T db sh -lc "mariadb-dump -uroot -p\"$MARIADB_ROOT_PASSWORD\" --single-transaction --routines --events --databases $DB_LIST" > "$db_sql"
gzip -9 "$db_sql"

log "Exporting media volume from web container"
# Stream archive to host to avoid bind-mount write permission issues inside the container.
$COMPOSE_CMD run --rm --no-deps web sh -lc 'cd /app/media && tar -cf - .' > "$media_tar"

log "Packing host files"
paths=""
if [ -d "$STATIC_DIR" ]; then
  paths="$paths $STATIC_DIR"
fi
if [ -d "$LOGS_DIR" ]; then
  paths="$paths $LOGS_DIR"
fi
if [ -d "$WALLABAG_IMG_DIR" ]; then
  paths="$paths $WALLABAG_IMG_DIR"
fi
if [ -d "$CRON_DIR" ]; then
  paths="$paths $CRON_DIR"
fi

if [ -n "$(printf '%s' "$paths" | tr -d ' ')" ]; then
  # shellcheck disable=SC2086
  tar -czf "$files_tar" $paths
else
  log "WARN: no host paths found; creating empty filesystem archive"
  tar -czf "$files_tar" --files-from /dev/null
fi

cat > "$meta_txt" <<EOF
run_id=$run_id
timestamp_utc=$now_utc
project_dir=$PROJECT_DIR
compose_cmd=$COMPOSE_CMD
db_list=$DB_LIST
static_dir=$STATIC_DIR
logs_dir=$LOGS_DIR
wallabag_img_dir=$WALLABAG_IMG_DIR
cron_dir=$CRON_DIR
EOF

log "Writing checksum manifest"
(
  cd "$work_dir"
  sha256sum db.sql.gz files.tar.gz media.tar meta.txt > manifest.sha256
)

log "Creating final archive $final_archive"
tar -czf "$final_archive" -C "$work_dir" db.sql.gz files.tar.gz media.tar meta.txt manifest.sha256

log "Pruning local backups (keep=$LOCAL_KEEP)"
ls -1dt "$out_dir"/${APP_NAME}-backup-*.tar.gz 2>/dev/null | awk "NR>$LOCAL_KEEP" | xargs -r rm -f

if [ -n "$REMOTE_TARGET" ]; then
  remote_file="$REMOTE_DIR_NORM/$(basename "$final_archive")"
  log "Backup server: $REMOTE_TARGET"
  log "Remote backup directory: $REMOTE_DIR_NORM"
  log "Uploading backup to $remote_file"
  # shellcheck disable=SC2086
  ssh $ssh_opts "$REMOTE_TARGET" "mkdir -p '$REMOTE_DIR_NORM'"
  # shellcheck disable=SC2086
  ssh $ssh_opts "$REMOTE_TARGET" "test -d '$REMOTE_DIR_NORM'"
  # shellcheck disable=SC2086
  echo "Uploading backup $final_archive to $REMOTE_TARGET:$remote_file"
  scp $ssh_opts "$final_archive" "$REMOTE_TARGET:$remote_file"

  log "Pruning remote backups (keep=$REMOTE_KEEP)"
  # shellcheck disable=SC2086
  ssh $ssh_opts "$REMOTE_TARGET" "ls -1dt '$REMOTE_DIR_NORM'/${APP_NAME}-backup-*.tar.gz 2>/dev/null | awk 'NR>$REMOTE_KEEP' | xargs -r rm -f"
else
  log "REMOTE_TARGET not set; skipping remote upload"
fi

log "Backup complete: $final_archive"
