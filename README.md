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
