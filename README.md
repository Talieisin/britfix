# Britfix

Convert American spellings to British English. Originally created to fix the US spelling output from LLMs, but useful for anyone who needs British spellings in their documents and code.

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
britfix --input file.txt
britfix --input "*.md" --recursive

# Process from stdin
echo "The color was analyzed" | britfix --quiet
# Output: The colour was analysed

# Interactive mode
britfix --input document.md --interactive

# Dry run
britfix --input "src/*.py" --dry-run
```

### Options

- `--input`: Input file(s) or pattern(s). If omitted, reads from stdin
- `--interactive`, `-i`: Interactive approval mode (strategy-aware — only suggests changes in regions the strategy considers safe, e.g. comments in code files, prose in markdown). JSON files fall back to non-interactive processing
- `--dry-run`: Preview changes without modifying files
- `--no-backup`: Skip backup creation
- `--recursive`: Process files recursively
- `--quiet`: Only output corrected text (for pipelines)

## File Type Strategies

Different file types are handled by different strategies, configured in `config.json`:

| Strategy | Extensions | Behaviour |
|----------|------------|-----------|
| **text** | `.txt` | Convert everything |
| **markdown** | `.md`, `.markdown`, `.mdown`, `.mkd`, `.mdx` | Preserve code spans and code blocks |
| **latex** | `.tex` | Skip LaTeX commands and math |
| **html** | `.html`, `.htm`, `.xml` | Skip HTML tags and `<style>`/`<script>` content |
| **css** | `.css`, `.scss`, `.sass`, `.less` | Only convert comments |
| **json** | `.json` | Only convert string values that contain whitespace (treats single-token strings as identifiers) |
| **code** | `.py`, `.js`, `.ts`, etc. | Only convert comments and docstrings |

### JSON File Handling

JSON values are corrected only when they contain whitespace. Single-token strings — `"center"`, `"colorScheme"`, `"src/Color.tsx"` — are treated as identifiers and left alone, since most JSON values in config files are programmatic, not prose. Multi-word values like `"The organization was reorganized"` are still corrected normally.

To opt out of JSON correction entirely, add `json:*` to your `.britfixignore` (see the [strategy escape hatch](#format) below).

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

## Ignoring Words (`.britfixignore`)

Create a `.britfixignore` file to prevent specific words from being converted. This is useful for words like "dialog", "color", or "center" that are conventional American spellings in technical contexts.

### Format

```text
# Global exceptions (all strategies)
dialog

# Wildcard — ignores 'dialog', 'dialogs', and any other dictionary
# entry starting with 'dialog'
dialog*

# Strategy-scoped exceptions (only apply to that file type)
code:color
code:center*
markdown:dialog

# Disable an entire strategy (escape hatch — equivalent to "ignore every
# word in JSON files")
json:*

# Phrase exceptions (quoted) — preserve a multi-word phrase verbatim
# while still correcting its constituent words elsewhere.
"mini program"
markdown:"mini program"
```

- One entry per line, `#` comments, blank lines skipped
- **Words** (bare, no quotes): `dialog`, `code:color`, optional `strategy:` prefix, optional trailing `*` for prefix wildcard (e.g. `color*` ignores `color`, `colors`, `colored`, `colorful`, `colorize`, etc.)
- **Phrases** (quoted): `"mini program"` or `markdown:"mini program"` preserves the literal phrase wherever it appears. Words inside the phrase span are not corrected; the same words appearing elsewhere are still corrected normally. Phrase matches are case-insensitive but the original casing of the matched span is preserved.
- A scoped bare `*` (e.g. `json:*`) disables that strategy entirely. Useful when a strategy is too broad for your project and you want to opt out without enumerating every word.
- A global bare `*` is invalid and ignored; it does not match anything or act as "ignore everything"
- Words use American (source) spelling (e.g. `color` not `colour`)
- All matches are case-insensitive

### File Discovery

Britfix walks up from the target file, stopping at the first `.git` boundary, the home directory, or the filesystem root (whichever is found first). It collects `.britfixignore` files from that boundary down to the file's directory, merging them additively.

### User-Level Config

A personal ignore file applies to all projects:

- **Linux/macOS**: `~/.config/britfix/ignore` (or `$XDG_CONFIG_HOME/britfix/ignore` if set)
- **Windows**: `%APPDATA%\britfix\ignore`

### Example

With this `.britfixignore` at your project root:
```text
dialog*
code:color*
code:center
```

Running britfix on a Python file:
```python
# The color is nice   ->  unchanged (code:color* exception)
# The dialogs work    ->  unchanged (global dialog* exception)
# The behavior is ok  ->  # The behaviour is ok (not excepted)
```

Running britfix on a Markdown file:
```text
The color is nice   ->  The colour is nice (color* is code-scoped, doesn't apply)
Open the dialog     ->  unchanged (global dialog* exception)
Open the dialogs    ->  unchanged (global dialog* wildcard covers inflected forms)
```

#### Phrase example

With `.britfixignore`:
```text
"mini program"
```

```text
Open the mini program now.    ->  unchanged ("program" is preserved inside the phrase)
The program is great.         ->  The programme is great. (standalone "program" still corrected)
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

The `britfix_hook.py` script integrates with tools that support hooks to automatically fix spellings when files are written.

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
            "command": "/absolute/path/to/britfix/run-hook.sh",
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
export BRITFIX_LOG=/tmp/britfix.log
```

Then watch: `tail -f /tmp/britfix.log`

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
