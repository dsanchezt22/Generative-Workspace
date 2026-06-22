#!/usr/bin/env bash
# End-of-task Python gate: lint + types + tests + deps. Advisory: reports on failure, never blocks.
set -uo pipefail
input=$(cat)
active=$(printf '%s' "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)
[[ "$active" == "true" ]] && exit 0          # loop guard
[[ -f pyproject.toml || -d .venv ]] || ls -- *.py >/dev/null 2>&1 || exit 0

TOOLBIN=""; [[ -d .venv/bin ]] && TOOLBIN=".venv/bin/"
SRC="src"; [[ -d "$SRC" ]] || SRC="."
tool(){ [[ -x "${TOOLBIN}$1" ]] && echo "${TOOLBIN}$1" || echo "$1"; }
log="$(mktemp)"; fail=0
run(){ local l="$1"; shift
  command -v "$1" >/dev/null 2>&1 || { echo "SKIP  $l" >>"$log"; return; }
  if "$@" >"/tmp/pg.$$.log" 2>&1; then echo "PASS  $l" >>"$log"
  else echo "FAIL  $l" >>"$log"; sed 's/^/      /' "/tmp/pg.$$.log" >>"$log"; fail=1; fi
  rm -f "/tmp/pg.$$.log"; }

run "lint  (ruff)"      "$(tool ruff)" check .
run "types (mypy)"      "$(tool mypy)" "$SRC"
run "tests (pytest)"    "$(tool pytest)"
run "deps  (pip-audit)" "$(tool pip-audit)"

report=$(cat "$log"); rm -f "$log"
if [[ $fail -ne 0 ]]; then
  # Advisory only: surface findings but never block the stop.
  { echo "Python quality gate (advisory) — issues found, not blocking:"; echo "$report"; } >&2
  jq -nc --arg r "Python quality gate found issues (advisory — not blocking). See hook output." '{systemMessage:$r}'
fi
exit 0
