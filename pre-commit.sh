#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ "$#" -gt 0 ]; then
  TARGETS=("$@")
else
  TARGETS=(README.md docs misc src tests scripts)
fi

if ! "$PYTHON_BIN" -c "import codespell" >/dev/null 2>&1; then
  echo "codespell is not installed. Install it with:" >&2
  echo "  $PYTHON_BIN -m pip install codespell" >&2
  exit 2
fi

if ! "$PYTHON_BIN" -c "import language_tool_python" >/dev/null 2>&1; then
  echo "language-tool-python is not installed. Install it with:" >&2
  echo "  $PYTHON_BIN -m pip install language-tool-python" >&2
  exit 2
fi

"$PYTHON_BIN" -m codespell "${TARGETS[@]}"
"$PYTHON_BIN" "$ROOT_DIR/scripts/extract_prose.py" "${TARGETS[@]}" \
  | "$PYTHON_BIN" "$ROOT_DIR/scripts/check_grammar.py" --language en-GB
