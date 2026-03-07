#!/bin/sh
set -eu

# Use an isolated virtual environment to avoid PEP 668 system-package restrictions.
VENV_DIR=".vercel-venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" -m venv "$VENV_DIR"

# Always run pip/manage.py through the venv interpreter (no shell activation required).
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install -r requirements.txt
"$VENV_DIR/bin/python" manage.py collectstatic --noinput
