#!/bin/sh
# Single in-container release task: the only migration owner in this repo.
# Runs inside a one-shot `compose run --rm --no-deps web` container.
# It only prepares schema and static files; it never starts any long-lived
# application process, never seeds data and never calls the network.
set -eu

cd /app/server
python /app/deploy/docker/wait_for_services.py
python manage.py migrate --noinput
python manage.py collectstatic --noinput
