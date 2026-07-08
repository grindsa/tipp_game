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
