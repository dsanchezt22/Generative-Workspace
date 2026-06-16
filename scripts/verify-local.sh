#!/usr/bin/env bash
#
# Quick health check: is Ollama serving, which models are present, and (if the
# backend is up) which model backend is active.
#
set -uo pipefail

PORT="${OLLAMA_PORT:-11434}"
HOST="http://localhost:${PORT}"

echo "Ollama:"
if curl -fsS --max-time 3 "$HOST/api/version" >/dev/null 2>&1; then
  echo "  ✓ serving on :$PORT  ($(curl -fsS "$HOST/api/version" 2>/dev/null))"
  models="$(ollama list 2>/dev/null | awk 'NR>1{print $1}' | paste -sd', ' -)"
  echo "  models: ${models:-<none pulled>}"
else
  echo "  ✗ not running — run:  make ollama-setup"
fi

echo "Backend (:8000):"
if curl -fsS --max-time 3 http://localhost:8000/api/llm/status >/dev/null 2>&1; then
  status="$(curl -fsS http://localhost:8000/api/llm/status 2>/dev/null)"
  if command -v python3 >/dev/null 2>&1; then
    printf '  '; printf '%s' "$status" | python3 -m json.tool 2>/dev/null | sed 's/^/  /' || echo "  $status"
  else
    echo "  $status"
  fi
else
  echo "  (not running — start with:  make dev-local)"
fi
