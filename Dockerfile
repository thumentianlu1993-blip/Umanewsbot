FROM python:3.12-slim

ARG UMANEWS_RELEASE_COMMIT=unknown
LABEL org.opencontainers.image.revision="${UMANEWS_RELEASE_COMMIT}"
ENV UMANEWS_RELEASE_COMMIT="${UMANEWS_RELEASE_COMMIT}"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY server /app/server
COPY runtime/tools /app/runtime/tools
COPY runtime/policies /app/runtime/policies
COPY docs/changes/realtime-race-results/source_registry_the_racing_api_free.json /app/runtime/policies/race_live/source_registry_the_racing_api_free.json
COPY deploy /app/deploy
COPY scripts /app/scripts
COPY .env.example /app/.env.example

RUN chmod +x /app/deploy/docker/*.sh /app/scripts/*.py \
    && mkdir -p /app/logs /app/server/staticfiles \
    && ln -s /app/runtime /app/server/runtime

WORKDIR /app/server

CMD ["/app/deploy/docker/start-web.sh"]
