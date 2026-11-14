#!/usr/bin/env bash
# Cursor runs project hooks from the repository root and pipes the event JSON
# to stdin. The event name is inside that JSON. otel-hook reads it only when
# invoked as `otel-hook --cursor`. A bare event name is a Click subcommand and
# exits 2 before any span is sent.
set -euo pipefail

export PATH="${HOME}/.local/bin:/usr/local/bin:${PATH}"

if [[ -z "${OTEL_EXPORTER_OTLP_PROTOCOL:-}" ]]; then
  export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
fi

endpoint="${OTEL_EXPORTER_OTLP_ENDPOINT:-}"
# A scheme and host with no path is not a Phoenix traces URL. The hook passes
# this variable through as the full HTTP URL, so the path has to be present.
if [[ -n "${endpoint}" && "${endpoint}" != *"://"*/*/* ]]; then
  echo "otel hook: OTEL_EXPORTER_OTLP_ENDPOINT has no path. Phoenix Cloud needs the traces URL, for example https://app.phoenix.arize.com/s/<space>/v1/traces" >&2
fi
# The hook passes this variable through as the full HTTP URL. Phoenix Cloud
# serves traces at a path that already ends in /v1/traces.
if [[ -n "${endpoint}" && "${endpoint}" != *"/v1/traces" && "${endpoint}" != *"/v1/traces/" ]]; then
  export OTEL_EXPORTER_OTLP_ENDPOINT="${endpoint%/}/v1/traces"
fi

if ! command -v otel-hook >/dev/null 2>&1; then
  python3 -m pip install --disable-pip-version-check --break-system-packages -q opentelemetry-hooks >&2 || true
fi

if command -v otel-hook >/dev/null 2>&1; then
  exec otel-hook --cursor
fi

if [[ -x "${HOME}/.local/bin/otel-hook" ]]; then
  exec "${HOME}/.local/bin/otel-hook" --cursor
fi

exec python3 -c 'import sys; from otel_hook import cli; sys.argv = ["otel-hook", "--cursor"]; raise SystemExit(cli())'
