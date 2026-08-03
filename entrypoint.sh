#!/bin/sh
set -e

python manage.py migrate --noinput

exec gunicorn django_intro_config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3
