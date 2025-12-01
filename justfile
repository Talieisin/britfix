# Spelling Fixer build commands

# Default recipe - show help
default:
    @just --list

# Install dependencies and sync environment
sync:
    uv sync

# Run the spelling fixer (development mode)
run *ARGS:
    uv run python spelling-fixer.py {{ARGS}}

# Build standalone executable
build: sync
    uv run --with pyinstaller pyinstaller \
        --onefile \
        --name spelling-fixer \
        --add-data "spelling-mapper.json:." \
        --add-data "config.json:." \
        --add-data "spell_checker_core.py:." \
        spelling-fixer.py
    @echo "Built: dist/spelling-fixer"

# Install to ~/.local/bin
install: build
    mkdir -p ~/.local/bin
    cp dist/spelling-fixer ~/.local/bin/
    @echo "Installed to ~/.local/bin/spelling-fixer"

# Install system-wide (requires sudo)
install-system: build
    sudo cp dist/spelling-fixer /usr/local/bin/
    @echo "Installed to /usr/local/bin/spelling-fixer"

# Run pytest test suite
test:
    uv run --with pytest pytest test_spelling_fixer.py -v

# Quick functional test
test-quick:
    @echo "=== Testing stdin (plain text - should convert color) ==="
    @echo "The color of the organization was analyzed." | uv run python spelling-fixer.py --quiet
    @echo ""
    @echo "=== Testing Python file (comments only) ==="
    @echo '# The color is nice' > /tmp/test-spell.py
    @uv run python spelling-fixer.py --input /tmp/test-spell.py --dry-run 2>&1 | tail -5

# Test the installed binary
test-binary:
    @echo "=== Testing installed binary ==="
    @which spelling-fixer
    @echo "The color was analyzed." | spelling-fixer --quiet

# Test the Claude Code hook
test-hook:
    @echo "=== Testing hook with markdown file ==="
    @echo "The color of the organization was analyzed." > /tmp/hook-test.md
    @echo '{"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": "/tmp/hook-test.md"}}' | \
        uv run python claude-spell-hook.py 2>&1
    @echo "File contents:"
    @cat /tmp/hook-test.md

# Clean build artifacts
clean:
    rm -rf build dist __pycache__ *.spec .venv uv.lock
    @echo "Cleaned build artifacts"
