#!/usr/bin/env sh
set -eu

# Parse one value from .env without executing the file.
read_env_value() {
  key="$1"
  file="$2"
  awk -v k="$key" '
    BEGIN { FS="=" }
    {
      line=$0
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
      if (line == "" || line ~ /^#/) next

      # KEY=value format
      if (line ~ "^" k "[[:space:]]*=") {
        sub("^" k "[[:space:]]*=[[:space:]]*", "", line)
      } else if (line ~ "^" k "[[:space:]]*:") {
        # KEY: value format (not shell-compatible, but common in copied env files)
        sub("^" k "[[:space:]]*:[[:space:]]*", "", line)
      } else {
        next
      }

      # Trim optional surrounding single or double quotes.
      gsub(/^["\047]|["\047]$/, "", line)
      print line
      exit
    }
  ' "$file"
}

# Prefer already exported environment values; otherwise read from .env.
if [ -z "${APP_UID:-}" ] && [ -f .env ]; then
  APP_UID="$(read_env_value APP_UID .env)"
fi

if [ -z "${APP_GID:-}" ] && [ -f .env ]; then
  APP_GID="$(read_env_value APP_GID .env)"
fi

if [ -z "${APP_UID:-}" ] || [ -z "${APP_GID:-}" ]; then
  echo "APP_UID and APP_GID must be set (for example in .env)." >&2
  exit 1
fi

echo "Fixing ownership for /app/static, /app/media, /app/logs to ${APP_UID}:${APP_GID}..."
docker compose run --rm --no-deps --user root web \
  sh -c 'chown -R "$APP_UID:$APP_GID" /app/static /app/media /app/logs'

echo "Ownership fix completed."
