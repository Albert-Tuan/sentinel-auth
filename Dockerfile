FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Copy all schema files (loaded into PostgreSQL, not the running app).
COPY infra/postgres/schema-core-v3.3.sql       ./schemas/schema-core-v3.3.sql
COPY infra/postgres/schema-detection-v3.3.sql  ./schemas/schema-detection-v3.3.sql
COPY infra/postgres/schema-ml-service-v3.3.sql ./schemas/schema-ml-service-v3.3.sql

ENV APP_ENV=development
# Trusted-proxy configuration.
# Safe default: only the local loopback address is trusted as a proxy source.
# X-Forwarded-For headers from any other peer are ignored by Uvicorn.
# Override this with the IP address(es) of your reverse proxy if deploying behind one.
# NEVER set FORWARDED_ALLOW_IPS="*": it would allow any remote client to forge
# X-Forwarded-For and bypass IP-based controls (rate limiting, MFA binding, etc.).
ENV FORWARDED_ALLOW_IPS=127.0.0.1
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
