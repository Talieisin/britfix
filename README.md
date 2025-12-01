# Spelling Fixer

A tool to convert American spellings to British English. Originally created to fix the US spelling output from LLMs like Claude, but useful for anyone who needs British spellings in their documents and code.

## Features

- **Multiple File Types**: Text, markdown, LaTeX, HTML, JSON, and code files
- **Programming Term Exclusions**: Preserves American spellings for common programming terms (e.g., `color`, `serialize`, `initialize`) in code files only
- **Interactive Mode**: Review and approve changes one by one
- **Claude Code Hook**: Automatically fix spellings as Claude writes files
- **Standalone Binary**: Build a single executable with no dependencies

## Installation

Requires [uv](https://github.com/astral-sh/uv) and optionally [just](https://github.com/casey/just).

```bash
# Install dependencies
just sync
# or: uv sync

# Build standalone binary and install to ~/.local/bin
just build && just install
```

## Usage

```bash
# Process files
spelling-fixer --input file.txt
spelling-fixer --input "*.md" --recursive

# Process from stdin
echo "The color was analyzed" | spelling-fixer --quiet
# Output: The colour was analysed

# Interactive mode
spelling-fixer --input document.md --interactive

# Dry run
spelling-fixer --input "src/*.py" --dry-run
```

### Options

- `--input`: Input file(s) or pattern(s). If omitted, reads from stdin
- `--interactive`, `-i`: Interactive approval mode
- `--dry-run`: Preview changes without modifying files
- `--no-backup`: Skip backup creation
- `--recursive`: Process files recursively
- `--quiet`: Only output corrected text (for pipelines)

## File Types

**Text files** (full conversion):
`.txt`, `.md`, `.tex`, `.html`, `.htm`, `.xml`, `.json`

**Code files** (programming exclusions applied):
`.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.java`, `.cpp`, `.c`, `.h`, `.hpp`, `.cs`, `.rb`, `.go`, `.rs`, `.swift`, `.kt`, `.scala`, `.php`, `.pl`, `.sh`

## Programming Exclusions

When processing code files, common programming terms are preserved in American spelling:

- `color`, `colored`, `colorize`
- `center`, `centered`
- `initialize`, `initialization`
- `serialize`, `serialization`
- `organize`, `organization`
- `normalize`, `synchronize`, `authorize`, etc.

Configure in `programming-exclusions.json`.

## Claude Code Hook

Automatically fix spellings when Claude Code writes files.

### Setup

1. Install dependencies: `just sync`

2. Add to `~/.claude/settings.json`:
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/spelling-fixer/run-hook.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

### Debugging

Enable logging by uncommenting in `run-hook.sh`:
```bash
export SPELL_HOOK_LOG=/tmp/spell-hook.log
```

Then watch: `tail -f /tmp/spell-hook.log`

## Development

```bash
just sync          # Install dependencies
just test          # Run tests
just test-hook     # Test Claude Code hook
just build         # Build standalone binary
just clean         # Remove build artifacts
```

## License

MIT
