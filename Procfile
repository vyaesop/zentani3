web: gunicorn jewelryshop.wsgi --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2}
worker: python manage.py run_tasks --forever
release: python manage.py migrate --noinput
