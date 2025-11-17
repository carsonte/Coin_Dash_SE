FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY coin_dash /app/coin_dash
COPY config /app/config
COPY data /app/data

RUN pip install --upgrade pip && pip install .

ENV TZ=UTC

ENTRYPOINT ["python", "-m", "coin_dash.cli"]

