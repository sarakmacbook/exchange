# P2P Merchant Price Bot — Docker
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# system deps
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py exchanges.py ./

# config & data are mounted as volumes; bot creates them if missing.
# For non-interactive docker, pass env vars: BOT_TOKEN, ADMIN_IDS, ASSET, FIAT, INTERVAL
# Example: docker run -e BOT_TOKEN=123:ABC -e ADMIN_IDS=123456 ...

VOLUME ["/app/data"]
# keep config.json & data.json in /app (or /app/data if you mount)

CMD ["python", "bot.py"]
