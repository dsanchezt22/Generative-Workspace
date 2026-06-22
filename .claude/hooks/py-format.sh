#!/usr/bin/env bash
# Format + lint the .py file Claude just edited.
set -uo pipefail
input=$(cat)
file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[[ "$file" == *.py && -f "$file" ]] || exit 0
RUFF="ruff"; [[ -x ".venv/bin/ruff" ]] && RUFF=".venv/bin/ruff"
command -v "$RUFF" >/dev/null 2>&1 || exit 0
"$RUFF" format "$file" >/dev/null 2>&1
"$RUFF" check --fix "$file" >/dev/null 2>&1
remaining=$("$RUFF" check "$file" 2>&1)
if [[ -n "$remaining" ]]; then
  { echo "Ruff still reports issues in $file — fix before continuing:"; echo "$remaining"; } >&2
  exit 2
fi
exit 0
