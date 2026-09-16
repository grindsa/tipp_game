#!/usr/bin/env sh
set -eu

# Update the tipp_game compose stack from origin/main.
#
# Usage: tipp_game_update.sh <web|stack>
#   web    rebuild the app image and recreate web
#   stack  pull db/wallabag images, rebuild the app image, recreate db, web, wallabag
#
# Always fast-forwards local main to origin/main before building.
# Build cache is pruned after the stack is up.
#
# The compose project defaults to /srv/stacks/tipp_game so this script can live
# in ~/scripts. Override with PROJECT_DIR if needed.

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
THIS_SCRIPT="$SCRIPT_DIR/$(basename -- "$0")"
DEFAULT_STACK_DIR="/srv/stacks/tipp_game"
GIT_REMOTE="${GIT_REMOTE:-origin}"
GIT_BRANCH="${GIT_BRANCH:-main}"

has_compose_file() {
  [ -f "$1/docker-compose.yml" ] || [ -f "$1/compose.yml" ]
}

resolve_project_dir() {
  if [ -n "${PROJECT_DIR:-}" ]; then
    printf '%s\n' "$PROJECT_DIR"
    return 0
  fi

  for candidate in \
    "$DEFAULT_STACK_DIR" \
    "$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)" \
    "$SCRIPT_DIR"
  do
    if has_compose_file "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

PROJECT_DIR="$(resolve_project_dir)" || {
  echo "ERROR: could not find docker-compose.yml. Set PROJECT_DIR (tried $DEFAULT_STACK_DIR)." >&2
  exit 1
}
COMPOSE_CMD="${COMPOSE_CMD:-docker compose --project-directory $PROJECT_DIR}"

usage() {
  echo "Usage: $0 <web|stack>" >&2
  echo "  web    rebuild and recreate the web service only" >&2
  echo "  stack  rebuild/recreate db, web, and wallabag" >&2
}

log() {
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '%s %s\n' "$ts" "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "ERROR: required command not found: $1"
    exit 1
  fi
}

SKIP_GIT=0
SCOPE=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --skip-git)
      SKIP_GIT=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    web|stack)
      if [ -n "$SCOPE" ]; then
        usage
        exit 1
      fi
      SCOPE="$1"
      ;;
    *)
      usage
      exit 1
      ;;
  esac
  shift
done

if [ -z "$SCOPE" ]; then
  usage
  exit 1
fi

require_cmd git
require_cmd docker

log "Using project directory $PROJECT_DIR"
cd "$PROJECT_DIR"

if ! has_compose_file "$PROJECT_DIR"; then
  log "ERROR: docker-compose.yml not found in $PROJECT_DIR"
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  log "ERROR: $PROJECT_DIR is not a git repository"
  exit 1
fi

update_from_github() {
  log "Fetching $GIT_REMOTE/$GIT_BRANCH"
  git fetch --prune "$GIT_REMOTE" "$GIT_BRANCH"

  if ! git diff --quiet || ! git diff --cached --quiet; then
    log "ERROR: working tree has local changes; commit, stash, or discard them first"
    git status --short
    exit 1
  fi

  git checkout "$GIT_BRANCH"
  before="$(git rev-parse HEAD)"
  git merge --ff-only "$GIT_REMOTE/$GIT_BRANCH"
  after="$(git rev-parse HEAD)"

  log "HEAD is $after ($(git log -1 --pretty=format:'%h %s'))"
  if [ "$before" != "$after" ]; then
    log "Updated $before -> $after; re-running this script"
    repo_script="$PROJECT_DIR/scripts/tipp_game_update.sh"
    if [ -f "$repo_script" ]; then
      exec "$repo_script" --skip-git "$SCOPE"
    fi
    exec "$THIS_SCRIPT" --skip-git "$SCOPE"
  fi
}

apply_migrations() {
  log "Applying database migrations"
  $COMPOSE_CMD run --rm jobs python manage.py migrate --noinput
}

prune_build_cache() {
  log "Pruning Docker build cache"
  docker builder prune --all --force
  docker image prune --force
}

if [ "$SKIP_GIT" -eq 0 ]; then
  update_from_github
else
  log "Skipping git update (already on $(git rev-parse --short HEAD))"
fi

case "$SCOPE" in
  web)
    log "Rebuilding web image without cache"
    $COMPOSE_CMD build --no-cache --pull web
    apply_migrations
    log "Recreating web"
    $COMPOSE_CMD up -d --force-recreate web
    ;;
  stack)
    log "Pulling db and wallabag images"
    $COMPOSE_CMD pull db wallabag
    log "Rebuilding web image without cache"
    $COMPOSE_CMD build --no-cache --pull web
    log "Recreating db"
    $COMPOSE_CMD up -d --force-recreate db
    apply_migrations
    log "Recreating web and wallabag"
    $COMPOSE_CMD up -d --force-recreate web wallabag
    ;;
esac

prune_build_cache

log "Stack status"
$COMPOSE_CMD ps
log "Update complete ($SCOPE)"
