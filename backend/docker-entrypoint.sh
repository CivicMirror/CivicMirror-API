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
    # Cloud Run requires a process listening on PORT; run a minimal health
    # server in the background alongside the Celery worker.
    echo "[entrypoint] worker: starting HTTP health server" >&2
    python3 -c "
import http.server, os
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
    def log_message(self, *a): pass
http.server.HTTPServer(('0.0.0.0', int(os.environ.get('PORT', 8080))), H).serve_forever()
" &
    echo "[entrypoint] worker: exec celery" >&2
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
