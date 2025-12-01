# Spelling Fixer

A tool to convert American spellings to British English. Originally created to fix the US spelling output from LLMs, but useful for anyone who needs British spellings in their documents and code.

## Features

- **Multiple File Types**: Text, markdown, LaTeX, HTML, JSON, and code files
- **Smart Code Handling**: Only converts comments and docstrings in code files, never string literals or identifiers
- **Context-Aware**: Preserves quoted text like `'colorScheme'` in comments (API references)
- **Interactive Mode**: Review and approve changes one by one
- **Hook Integration**: Automatically fix spellings when writing files

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

## File Type Strategies

Different file types are handled by different strategies, configured in `config.json`:

| Strategy | Extensions | Behaviour |
|----------|------------|-----------|
| **text** | `.txt`, `.md` | Convert everything |
| **latex** | `.tex` | Skip LaTeX commands and math |
| **html** | `.html`, `.htm`, `.xml` | Skip HTML tags |
| **json** | `.json` | Only convert string values |
| **code** | `.py`, `.js`, `.ts`, etc. | Only convert comments and docstrings |

### Code File Handling

For code files, the tool intelligently handles context:

**Converted** (prose in comments/docstrings):
```python
# The behavior is favorable  ->  # The behaviour is favourable
"""This optimizes the color."""  ->  """This optimises the colour."""
```

**NOT converted** (code and API references):
```python
config.get('organization')      # String literal - unchanged
payload = {'colorScheme': x}    # Dict key - unchanged  
# Use 'colorField' for the API  # Quoted in comment - unchanged
```

## Configuration

Edit `config.json` to customise file type handling:

```json
{
  "strategies": {
    "code": {
      "extensions": [".py", ".js", ".ts", ...]
    }
  }
}
```

## Hook Integration

The `claude-spell-hook.py` script integrates with tools that support hooks to automatically fix spellings when files are written.

### Setup

1. Install dependencies: `just sync`

2. Configure your tool to call the hook. Example for settings:
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
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
just test-hook     # Test hook
just build         # Build standalone binary
just clean         # Remove build artefacts
```

## License

MIT
