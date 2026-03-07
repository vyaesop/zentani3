#!/bin/sh
set -eu

# Use an isolated virtual environment to avoid PEP 668 system-package restrictions.
python3 -m venv .vercel-venv
. .vercel-venv/bin/activate

python -m pip install --upgrade pip
# Python 3.12 removed stdlib distutils; setuptools provides the compatibility shim.
python -m pip install setuptools
python -m pip install -r requirements.txt
python manage.py collectstatic --noinput
