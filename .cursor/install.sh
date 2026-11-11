#!/usr/bin/env bash
set -euo pipefail

python3 -m pip install --upgrade pip --break-system-packages
python3 -m pip install --break-system-packages -r mcps/rewrite-news/requirements.txt

if [[ -f web/package-lock.json ]]; then
  npm ci --prefix web
fi
