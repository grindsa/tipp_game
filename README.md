# tipp_game

Legacy Django tip-game application being renovated stepwise.

## Current Baseline

- Python target for modernization: 3.13
- Django target during transition: 4.x compatible settings
- Containerized with Dockerfile and docker-compose

## Quick Start (Local)

1. Copy environment template:
   cp .env.example .env
2. Adjust values in .env (especially secrets and database credentials).
3. Create and activate virtual environment.
4. Install dependencies:
   pip install -r app/requirements.txt
5. Run checks:
   python app/manage.py check
6. Start server:
   python app/manage.py runserver 0.0.0.0:8000

## Test Coverage

Run coverage for Django tests with one helper script:

- `./scripts/coverage.sh` (runs all `app/tests` targets)
- `./scripts/coverage.sh tests.test_update_presseschau` (single target)

The script uses:

- Python from `.venv`
- `app/.coveragerc`
- default env `DJANGO_ENV=development` and `DJANGO_SECRET_KEY=test-secret`

After the run:

- terminal report is printed
- HTML report is generated at `app/htmlcov/index.html`

## Quick Start (Docker Compose)

1. Copy environment template:
   cp .env.example .env
2. Ensure external network exists if you use the default compose config:
   docker network create tg
3. Build and start:
   docker compose up --build

App is exposed on port 8000.

## Notes

- The project uses MySQL/MariaDB and a secondary wallabag database connection.
- For development and CI, values are sourced via environment variables.
- Backup artifacts (.old/.bak/.bup) are intentionally excluded from source control.

## Deployment Notes

- The web service runs collectstatic automatically before gunicorn starts.
- Static files are persisted on the host at /srv/data/tipp_game/static (mounted to /app/static).
- Ensure /srv/data/tipp_game/static exists and is writable by APP_UID:APP_GID before startup.
- Django admin files under app/static/admin are generated artifacts and should not be committed to git.
- The image user is created from APP_UID/APP_GID build args to keep file ownership stable across container restarts.
- If you changed APP_UID/APP_GID or reused an old static/media volume, run a one-time ownership fix from root before starting web.
- Helper script for ownership reset:
   ./scripts/fix-volume-permissions.sh
   The script reads APP_UID/APP_GID directly from .env and does not require shell-compatible formatting for other variables.
- After deploy or upgrade, verify static assets if admin styling looks broken:
   docker compose logs -f web

## Backup

Backup tooling is provided via host scripts:

- `scripts/backup.sh`: core backup workflow (DB dump + filesystem/media archives + checksums + optional SCP upload)
- `scripts/backup.manual.sh`: manual wrapper for on-demand runs
- `scripts/restore.sh`: restore workflow from a generated backup archive
- `scripts/backup.cron.example`: cron template for the 2nd Friday schedule

Config validation (non-destructive):

- `./scripts/backup.sh --check-config`
- `./scripts/backup.manual.sh --check-config`

This mode resolves variables from `.env`, validates key prerequisites, prints the effective backup configuration, and exits without creating backup artifacts.

Recommended schedule (2nd Friday, 02:00):

- `0 2 8-14 * 5`

Cron integration:

- Use the example line in `scripts/backup.cron.example`.
- The cron command executes `scripts/backup.manual.sh`.
- `scripts/backup.sh` reads `.env` directly and supports both `KEY=value` and `KEY: value` formats.

Backup-related `.env` variables:

- `BACKUP_ROOT` (optional, default `/tmp/tipp_game-backups`): local directory where backup archives are written.
- `REMOTE_TARGET` (optional): backup target in `user@host` format. If empty, upload is skipped.
- `REMOTE_DIR` (optional, default `/srv/backups/tipp_game`): remote destination directory.
- `SSH_KEY` (optional): absolute path to private key used for `ssh/scp`.
- `LOCAL_KEEP` (optional, default `3`): number of local archives to retain.
- `REMOTE_KEEP` (optional, default `12`): number of remote archives to retain.
- `WA_ADMIN_NUMBER` (optional, default empty): WhatsApp destination number for final status notifications.
- `WA_SRV` (optional): WhatsApp server used for notification transport.
- `WA_PORT` (optional): WhatsApp server port used for notification transport.
- `WA_NOTIFY_NUMBER` (optional): destination override. Falls back to `WA_ADMIN_NUMBER`.
- `WA_NOTIFY_SRV` (optional): server override. Falls back to `WA_SRV`.
- `WA_NOTIFY_PORT` (optional): port override. Falls back to `WA_PORT`.

The backup requires DB settings from `.env` (`MARIADB_ROOT_PASSWORD`, `MARIADB_DATABASE`, and optional `WB_DATABASE`).

## One-Shot Jobs Cron Export (PoC)

The script [app/tools/cron_create.py](app/tools/cron_create.py) can be run in a one-shot container and write a cron file to a mounted host path.

Environment variables:

- `CRON_TARGET_PATH`: full output path for the generated cron file (highest priority)
- `CRON_TARGET_DIR` + `CRON_TARGET_FILE`: output directory and filename if `CRON_TARGET_PATH` is not set
- `CRON_EXECUTION_PREFIX`: optional command prefix added to each generated entry

Why `CRON_EXECUTION_PREFIX` matters:

- The generated cron file is consumed by host cron.
- Commands inside that file must be executable on the host.
- Use a prefix such as `docker compose ... run --rm jobs python` so each entry starts a one-shot job container.

Example (concept):

- `CRON_TARGET_DIR=/app/cron_out`
- `CRON_TARGET_FILE=tippgame`
- `CRON_EXECUTION_PREFIX=docker compose --project-directory /srv/data/tipp_game run --rm jobs python`

Then run once per day:

- `docker compose run --rm jobs python tools/cron_create.py`

This requires mounting a host directory (for example `/srv/data/tipp_game/cron`) into the jobs container at `/app/cron_out`.
