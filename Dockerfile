# Django 6 requires Python >= 3.12, so we use 3.12-slim rather than 3.11-slim
# while keeping the same "slim" footprint the brief asks for.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=django_intro_config.settings

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

# collectstatic needs *a* SECRET_KEY but no live database. DEBUG must match
# the runtime value (False) since it picks the static storage backend
# (manifest vs. plain) -- collectstatic under the wrong one leaves the
# manifest whitenoise needs to serve hashed assets missing at runtime.
RUN SECRET_KEY=build-time-only DEBUG=False python manage.py collectstatic --noinput

RUN addgroup --system app \
    && adduser --system --ingroup app --home /app app \
    && chown -R app:app /app

USER app

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
