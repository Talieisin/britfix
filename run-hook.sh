#!/bin/bash
# Britfix hook wrapper
# To enable logging, uncomment the next line:
# export BRITFIX_LOG=/tmp/britfix.log

# Get the directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"
exec uv run python britfix_hook.py
