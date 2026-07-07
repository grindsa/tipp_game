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
- The named volume mounted at /app/static starts empty on fresh deployments, so collectstatic is required.
- Django admin files under app/static/admin are generated artifacts and should not be committed to git.
- The image user is created from APP_UID/APP_GID build args to keep file ownership stable across container restarts.
- If you changed APP_UID/APP_GID or reused an old static/media volume, run a one-time ownership fix from root before starting web.
- Helper script for ownership reset:
   ./scripts/fix-volume-permissions.sh
- After deploy or upgrade, verify static assets if admin styling looks broken:
   docker compose logs -f web
