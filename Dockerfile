FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY server /app/server
COPY .env.example /app/.env.example

WORKDIR /app/server

RUN python manage.py collectstatic --noinput

CMD ["gunicorn", "app.wsgi:application", "--bind", "0.0.0.0:8000"]
