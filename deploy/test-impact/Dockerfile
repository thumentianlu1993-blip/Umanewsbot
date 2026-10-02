FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3.12 python3.12-venv postgresql-16 postgresql-client-16 curl ca-certificates git ruby && rm -rf /var/lib/apt/lists/*
RUN python3.12 -m venv /venv
COPY requirements.txt /tmp/requirements.txt
RUN /venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt
RUN useradd --uid 10001 --create-home tester
ENV PATH=/venv/bin:/usr/lib/postgresql/16/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/bin/bash", "/source/deploy/test-impact/entrypoint.sh"]
