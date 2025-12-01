# Britfix build commands

# Default recipe - show help
default:
    @just --list

# Install dependencies and sync environment
sync:
    uv sync

# Run britfix (development mode)
run *ARGS:
    uv run python britfix.py {{ARGS}}

# Build standalone executable
build: sync
    uv run --with pyinstaller pyinstaller \
        --onefile \
        --name britfix \
        --add-data "spelling-mapper.json:." \
        --add-data "config.json:." \
        --add-data "britfix_core.py:." \
        britfix.py
    @echo "Built: dist/britfix"

# Install to ~/.local/bin
install: build
    mkdir -p ~/.local/bin
    cp dist/britfix ~/.local/bin/
    @echo "Installed to ~/.local/bin/britfix"

# Install system-wide (requires sudo)
install-system: build
    sudo cp dist/britfix /usr/local/bin/
    @echo "Installed to /usr/local/bin/britfix"

# Run pytest test suite
test:
    uv run --with pytest pytest test_britfix.py -v

# Quick functional test
test-quick:
    @echo "=== Testing stdin (plain text - should convert color) ==="
    @echo "The color of the organization was analyzed." | uv run python britfix.py --quiet
    @echo ""
    @echo "=== Testing Python file (comments only) ==="
    @echo '# The color is nice' > /tmp/test-britfix.py
    @uv run python britfix.py --input /tmp/test-britfix.py --dry-run 2>&1 | tail -5

# Test the installed binary
test-binary:
    @echo "=== Testing installed binary ==="
    @which britfix
    @echo "The color was analyzed." | britfix --quiet

# Test the hook
test-hook:
    @echo "=== Testing hook with markdown file ==="
    @echo "The color of the organization was analyzed." > /tmp/hook-test.md
    @echo '{"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": "/tmp/hook-test.md"}}' | \
        uv run python britfix_hook.py 2>&1
    @echo "File contents:"
    @cat /tmp/hook-test.md

# Clean build artifacts
clean:
    rm -rf build dist __pycache__ *.spec .venv uv.lock
    @echo "Cleaned build artefacts"
