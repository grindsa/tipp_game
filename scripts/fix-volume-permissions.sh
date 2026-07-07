#!/usr/bin/env sh
set -eu

# Load .env if present so APP_UID/APP_GID are available outside compose interpolation.
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

if [ -z "${APP_UID:-}" ] || [ -z "${APP_GID:-}" ]; then
  echo "APP_UID and APP_GID must be set (for example in .env)." >&2
  exit 1
fi

echo "Fixing ownership for /app/static, /app/media, /app/logs to ${APP_UID}:${APP_GID}..."
docker compose run --rm --no-deps --user root web \
  sh -c 'chown -R "$APP_UID:$APP_GID" /app/static /app/media /app/logs'

echo "Ownership fix completed."
