#!/usr/bin/env bash
set -euo pipefail

if ! python3 -c "import venv" >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y python3-venv
fi

python3 -m venv mcps/rewrite-news/.venv
mcps/rewrite-news/.venv/bin/pip install --upgrade pip
mcps/rewrite-news/.venv/bin/pip install -r mcps/rewrite-news/requirements.txt

if [[ -f web/package-lock.json ]]; then
  npm ci --prefix web
fi
