#!/bin/sh
set -eu

# Use an isolated virtual environment to avoid PEP 668 system-package restrictions.
python3 -m venv .vercel-venv
. .vercel-venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py collectstatic --noinput
