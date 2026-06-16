#!/usr/bin/env bash
#
# Trus — one-command local LLM setup.
#
# Installs Ollama (if needed), starts its server, pulls a model, and wires the
# repo .env so the backend generates with the LOCAL model (zero API cost).
# Safe to re-run: every step is idempotent.
#
#   bash scripts/setup-ollama.sh          # defaults
#   OLLAMA_MODEL=qwen2.5:7b-instruct bash scripts/setup-ollama.sh   # pick a model
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
EXAMPLE="$ROOT/.env.example"

# Primary model + ordered fallbacks (all verified to exist in the Ollama library).
MODEL="${OLLAMA_MODEL:-qwen3:4b-instruct-2507-q4_K_M}"
FALLBACKS=("qwen3:4b-instruct" "qwen2.5:7b-instruct" "qwen2.5:3b-instruct")
PORT="${OLLAMA_PORT:-11434}"
HOST="http://localhost:${PORT}"
BASE_URL="${HOST}/v1"

say()  { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

server_up() { curl -fsS --max-time 2 "$HOST/api/version" >/dev/null 2>&1; }
have_model() { ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$1"; }

# 1 ── Install Ollama ─────────────────────────────────────────────────────────
if command -v ollama >/dev/null 2>&1; then
  ok "Ollama already installed ($(ollama --version 2>&1 | head -1))"
else
  say "Installing Ollama…"
  if [ "$(uname -s)" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
    brew install ollama
  else
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  command -v ollama >/dev/null 2>&1 || die "Ollama installed but 'ollama' isn't on PATH — open a new shell and re-run."
  ok "Ollama installed."
fi

# 2 ── Start the server ───────────────────────────────────────────────────────
if server_up; then
  ok "Ollama server already running on :$PORT"
else
  say "Starting Ollama server in the background…"
  mkdir -p "$ROOT/.ollama-logs"
  nohup ollama serve >"$ROOT/.ollama-logs/serve.log" 2>&1 &
  for _ in $(seq 1 30); do if server_up; then break; fi; sleep 1; done
  server_up || die "Server didn't come up — see $ROOT/.ollama-logs/serve.log"
  ok "Ollama server running on :$PORT"
fi

# 3 ── Pull a model (primary, then fallbacks) ─────────────────────────────────
pulled=""
for tag in "$MODEL" "${FALLBACKS[@]}"; do
  if have_model "$tag"; then ok "Model already present: $tag"; MODEL="$tag"; pulled=1; break; fi
  say "Pulling $tag … (first run downloads a few GB — this is the slow part)"
  if ollama pull "$tag"; then ok "Pulled $tag"; MODEL="$tag"; pulled=1; break; fi
  warn "Couldn't pull $tag — trying a fallback."
done
[ -n "$pulled" ] || die "Could not pull any model. Check your network and retry."

# 4 ── Wire .env (managed block; never clobbers your other keys) ──────────────
if [ ! -f "$ENV_FILE" ]; then
  cp "$EXAMPLE" "$ENV_FILE" 2>/dev/null || : >"$ENV_FILE"
  say "Created .env"
fi
tmp="$(mktemp)"
awk '
  /^# >>> trus local-ollama >>>/ {skip=1}
  /^# <<< trus local-ollama <<</ {skip=0; next}
  skip!=1 {print}
' "$ENV_FILE" >"$tmp"
{
  cat "$tmp"
  printf '\n# >>> trus local-ollama >>> (managed by scripts/setup-ollama.sh)\n'
  printf 'TRUS_LLM_PROVIDER=openai\n'
  printf 'TRUS_LLM_BASE_URL=%s\n' "$BASE_URL"
  printf 'TRUS_LLM_MODEL=%s\n' "$MODEL"
  printf 'TRUS_LLM_JSON_MODE=object\n'
  printf '# <<< trus local-ollama <<<\n'
} >"$ENV_FILE"
rm -f "$tmp"
ok ".env wired → provider=openai · model=$MODEL · endpoint=$BASE_URL"

# 5 ── Smoke-test the local model end-to-end ──────────────────────────────────
say "Smoke-testing the local model…"
resp="$(curl -fsS --max-time 90 "$BASE_URL/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly one word: ready\"}],\"stream\":false}" 2>/dev/null || true)"
if printf '%s' "$resp" | grep -qi "ready"; then
  ok "Local model responded correctly. 🎉"
else
  warn "Smoke test was inconclusive (the model may still be fine):"
  printf '   %s\n' "$(printf '%s' "$resp" | head -c 200)"
fi

cat <<EOF

$(ok "Local Ollama is ready.")
  Model:     $MODEL
  Endpoint:  $BASE_URL
  Next:
    make verify-local     # check Ollama + backend
    make dev-local        # run the backend against the local model
    (frontend)  cd frontend && npm run dev
  Keep it running across reboots:  brew services start ollama
EOF
