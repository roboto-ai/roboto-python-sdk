#!/usr/bin/env bash
set -euo pipefail

SERVER_NAME="knowledge-base-roboto"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "-n" ]]; then
  DRY_RUN=true
fi

if $DRY_RUN; then
  echo "[dry run] Would remove MCP server '$SERVER_NAME'"
  echo "[dry run] Would delete $SCRIPT_DIR"
  exit 0
fi

claude mcp remove "$SERVER_NAME" 2>/dev/null || true
rm -rf "$SCRIPT_DIR"
echo "Removed server '$SERVER_NAME' and $SCRIPT_DIR"
