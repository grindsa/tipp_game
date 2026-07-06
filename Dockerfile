FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Build-time dependencies for packages with native extensions.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    default-libmysqlclient-dev \
    libsodium-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt /build/requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel && \
    pip wheel --wheel-dir /wheels -r /build/requirements.txt


FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Runtime libraries only.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmariadb3 \
    libsodium23 \
    && rm -rf /var/lib/apt/lists/* && \
    groupadd --system app && useradd --system --gid app --create-home --home-dir /home/app app

COPY --from=builder /wheels /wheels
COPY app/requirements.txt /app/requirements.txt

RUN pip install --no-index --find-links=/wheels -r /app/requirements.txt && \
    rm -rf /wheels

COPY ./app /app/

RUN chown -R app:app /app

USER app

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "tipp_game.wsgi:application"]

