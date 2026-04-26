from __future__ import annotations

import os
import time

import psycopg
import redis


def wait_for_postgres() -> None:
    if os.getenv("DB_ENGINE", "sqlite").lower() != "postgres":
        return
    dsn = (
        f"dbname={os.getenv('POSTGRES_DB', 'horse_news')} "
        f"user={os.getenv('POSTGRES_USER', 'horse_news')} "
        f"password={os.getenv('POSTGRES_PASSWORD', '')} "
        f"host={os.getenv('POSTGRES_HOST', 'db')} "
        f"port={os.getenv('POSTGRES_PORT', '5432')} "
        f"connect_timeout={os.getenv('POSTGRES_CONNECT_TIMEOUT', '10')}"
    )
    last_error = None
    for _ in range(30):
        try:
            with psycopg.connect(dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            return
        except Exception as exc:  # pragma: no cover - startup polling
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"PostgreSQL is not ready: {last_error}")


def wait_for_redis() -> None:
    broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    last_error = None
    for _ in range(30):
        try:
            client = redis.Redis.from_url(broker_url)
            client.ping()
            return
        except Exception as exc:  # pragma: no cover - startup polling
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Redis is not ready: {last_error}")


if __name__ == "__main__":
    wait_for_postgres()
    wait_for_redis()

