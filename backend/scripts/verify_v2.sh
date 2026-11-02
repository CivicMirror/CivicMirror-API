#!/bin/sh
set -eu

python -c 'import sys; assert sys.version_info[:2] == (3, 13), sys.version'
python manage.py check --settings=config.settings.v2
python manage.py makemigrations --check --dry-run --settings=config.settings.v2
ruff check . --extend-exclude sqlcheck.py
# STORAGES['staticfiles'] is whitenoise's CompressedManifestStaticFilesStorage whenever
# whitenoise is importable, so admin tests that render widget media need a built manifest.
# Without this, cm2_review admin tests fail with "Missing staticfiles manifest entry".
python manage.py collectstatic --noinput --settings=config.settings.v2
python -m pytest -c pytest-v2.ini
