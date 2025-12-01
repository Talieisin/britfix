#!/bin/bash
# Claude Code hook wrapper for spelling-fixer
# To enable logging, uncomment the next line:
# export SPELL_HOOK_LOG=/tmp/spell-hook.log

# Get the directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"
exec uv run python claude-spell-hook.py
