#!/bin/sh
set -e

case "$1" in
  api)
    exec gunicorn config.wsgi:application \
      --bind "0.0.0.0:${PORT:-8080}" \
      --workers "${GUNICORN_WORKERS:-2}" \
      --timeout "${GUNICORN_TIMEOUT:-120}" \
      --access-logfile - \
      --error-logfile -
    ;;
  worker)
    exec celery -A config worker \
      --loglevel "${CELERY_LOG_LEVEL:-INFO}" \
      --concurrency "${CELERY_CONCURRENCY:-2}"
    ;;
  migrate)
    exec python manage.py migrate --noinput
    ;;
  *)
    exec "$@"
    ;;
esac
