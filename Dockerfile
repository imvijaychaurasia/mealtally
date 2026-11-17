# syntax=docker/dockerfile:1.7
# SPDX-License-Identifier: AGPL-3.0-only
#
# Multi-stage build for linux/amd64 and linux/arm64.
#   runtime (default): the production image, non-root, static files collected at build time.
#   dev:               the same dependencies plus the dev group (pytest, ruff); `make test` and CI use it.

# --- CSS: Tailwind standalone CLI (no Node anywhere); only the compiled file reaches the image ---------------------
FROM debian:bookworm-slim AS css
ARG TARGETARCH
ARG TAILWIND_VERSION=v4.3.5
RUN apt-get update && apt-get install --no-install-recommends -y curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) arch=x64;   sum=e47695cee3f0d90623a91f3939b08bdee610eb5ad99340adff9d4145b284d6cc ;; \
      arm64) arch=arm64; sum=ffcd0d21dbd7c605dc12743ff0c0b47debc963c86b399674084c1c8f2c96ecad ;; \
      *) echo "unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/tailwindcss \
      "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-${arch}"; \
    echo "${sum}  /usr/local/bin/tailwindcss" | sha256sum -c -; \
    chmod +x /usr/local/bin/tailwindcss
WORKDIR /src
COPY mealtally/web mealtally/web
COPY mealtally/preview mealtally/preview
COPY mealtally/static/js mealtally/static/js
RUN tailwindcss -i mealtally/web/tailwind/input.css -o /out/app.css --minify

# --- Python dependencies ---------------------------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
RUN apt-get update && apt-get install --no-install-recommends -y build-essential libpq-dev gettext \
  && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-install-project --no-dev
COPY . /app
COPY --from=css /out/app.css /app/mealtally/static/css/app.css
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev
RUN cd /app && /opt/venv/bin/django-admin compilemessages --ignore=.venv

# --- dev: tests and tooling (the source is bind-mounted over /app by compose) --------------------------------------
FROM build AS dev
RUN apt-get update && apt-get install --no-install-recommends -y wait-for-it libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core \
  && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=config.settings.test
COPY docker/django/ /docker/
RUN chmod +x /docker/*
ENTRYPOINT ["/docker/entrypoint"]

# --- runtime: the production image ----------------------------------------------------------------------------------
FROM python:3.14-slim-bookworm AS runtime
LABEL org.opencontainers.image.title="Mealtally" \
      org.opencontainers.image.description="Prepaid meal passes and meal subscriptions for restaurants, messes and tiffin services" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
RUN apt-get update && apt-get install --no-install-recommends -y libpq5 wait-for-it \
      libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core postgresql-client \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --system --gid 10001 mealtally \
  && useradd --system --uid 10001 --gid mealtally --home /home/mealtally --create-home mealtally
WORKDIR /app
COPY --from=build --chown=mealtally:mealtally /opt/venv /opt/venv
COPY --from=build --chown=mealtally:mealtally /app /app
COPY --chown=mealtally:mealtally docker/django/ /docker/
RUN chmod +x /docker/* && mkdir -p /app/mealtally/media /backups && chown mealtally:mealtally /app/mealtally/media /backups
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=config.settings.production
# Static files are collected at build time (WhiteNoise serves them); no secrets are needed for that step.
RUN DJANGO_SECRET_KEY=build-only POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x \
    python manage.py collectstatic --noinput --verbosity 0 && chown -R mealtally:mealtally /app/staticfiles
USER mealtally
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=6s --start-period=90s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=4)" || exit 1
ENTRYPOINT ["/docker/entrypoint"]
CMD ["/docker/start-web"]
