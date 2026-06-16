#!/usr/bin/env bash
#
# Run the Trus backend against the local Ollama model. Ensures the Ollama server
# is up first (starting it if Ollama is installed but not serving).
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${OLLAMA_PORT:-11434}"
HOST="http://localhost:${PORT}"

server_up() { curl -fsS --max-time 2 "$HOST/api/version" >/dev/null 2>&1; }

if ! server_up; then
  if command -v ollama >/dev/null 2>&1; then
    echo "Starting Ollama…"
    mkdir -p "$ROOT/.ollama-logs"
    nohup ollama serve >"$ROOT/.ollama-logs/serve.log" 2>&1 &
    for _ in $(seq 1 20); do if server_up; then break; fi; sleep 1; done
  fi
fi
server_up || { echo "Ollama isn't running. Run:  make ollama-setup"; exit 1; }

cd "$ROOT/backend"
[ -d .venv ] && source .venv/bin/activate
echo "Backend → http://localhost:8000  (model backend: $(curl -fsS http://localhost:8000/api/llm/status 2>/dev/null || echo 'starting…'))"
exec uvicorn src.main:app --reload
