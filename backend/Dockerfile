# Trus backend — production image (R-906).
# Build from the repo root's `deploy/fly.toml.example`, or directly:
#   docker build -t trus-backend -f backend/Dockerfile backend/
FROM python:3.12-slim
WORKDIR /app

# Dependencies layer first so `docker build` only reinstalls when
# requirements.txt changes, not on every source edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

# Runtime secrets (SESSION_SECRET, TRUS_OPS_TOKEN, GEMINI_API_KEY) are injected
# by the platform (e.g. `fly secrets set`) — never baked into the image.
# TRUS_CORS_ORIGINS / TRUS_PUBLIC_URL are deployment-specific — set at deploy
# time too. See deploy/README.md.
ENV TRUS_ENV=prod \
    TRUS_ALLOW_ANON=0 \
    TRUS_COOKIE_SECURE=1 \
    TRUS_DB_PATH=/data/trus.db

# Non-root: SQLite lives on the mounted /data volume, owned by this user.
RUN useradd --create-home --uid 1000 trus \
    && mkdir -p /data \
    && chown -R trus:trus /data /app
USER trus

EXPOSE 8080
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
