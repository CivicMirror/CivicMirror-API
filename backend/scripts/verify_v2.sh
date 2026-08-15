#!/bin/sh
set -eu

python -c 'import sys; assert sys.version_info[:2] == (3, 13), sys.version'
python manage.py check --settings=config.settings.v2
python manage.py makemigrations --check --dry-run --settings=config.settings.v2
ruff check . --extend-exclude sqlcheck.py
python -m pytest -c pytest-v2.ini
