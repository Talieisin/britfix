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
| **markdown** | `.md`, `.markdown`, `.mdown`, `.mkd`, `.mdx` | Preserve code, blockquotes, HTML markup, URLs, and Markdown link/reference targets |
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

Create a `.britfixignore` file to prevent specific words from being converted. This is useful for words like "dialogue", "colour", or "centre" that are conventional American spellings in technical contexts.

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

### Excluding paths (hook only)

`exclude_paths` is a list of substrings matched against each written file's
resolved absolute path (in forward-slash form, so entries work on any
platform). If any substring is found in the path, the hook skips the file
entirely. Use it to protect content that must stay verbatim (transcripts,
quoted source text) which the word-level ignore files cannot cover:

```json
{
  "exclude_paths": ["/Transcripts/", "/quoted-sources/"]
}
```

Notes:

- Matching is naive, case-sensitive substring: `notes` also matches
  `footnotes`, so prefer a distinctive fragment like `/Transcripts/`.
- Entries must be non-empty strings. An invalid value (wrong type, or an
  empty string, which would match every path) is a fatal config error: the
  hook refuses to run rather than silently processing files you asked it to
  protect.
- This only affects the hook; the `britfix` CLI processes whatever it is
  given.

### Local overrides (`config.local.json`)

To keep private paths out of the repo, create a gitignored `config.local.json`
next to `config.json`. Its `exclude_paths` entries are appended to the shared
list:

```json
{
  "exclude_paths": ["/Users/me/Private/Transcripts/"]
}
```

The local file may only set `exclude_paths` (and comment keys). Anything
else, in particular `strategies`, is a fatal config error: strategies must stay
in the shared `config.json`, which the CLI also reads, so a hook-only
override would make the two disagree about how a file should be handled. The
file is never bundled into the built binary.

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

## Licence

MIT

### Markdown references and URLs

Bare HTTP(S) URLs, including query strings, fragments and balanced parentheses, are preserved. Apostrophes inside a URL remain URI data. Inline and image destinations and reference identifiers are preserved; collapsed and shortcut labels remain unchanged where visible text also identifies the reference. Ordinary link text and surrounding prose still convert. HTML comments and script/style bodies are preserved.

### Markdown quotations

**New default:** explicit italicised quotations (`*"color"*` or `_“color”_`) are now preserved verbatim. This extends the existing blockquote protection; ordinary italic emphasis still converts.

Ordinary unformatted quotations retain their previous conversion behaviour. To preserve them too, set `strategies.markdown.preserve_quoted_prose` to `true` in `config.json` (boolean, default `false`). This intentionally misses spelling corrections within quoted prose. Unclosed double/curly quotations preserve the remainder of their paragraph; straight single quotes require a pair, so leading elisions and decades do not hide the remainder of a paragraph.

### Python and file preservation

Python files use tokenisation and AST docstring identification while retaining the `code:` ignore namespace. Non-docstring string literals, executable tokens, shebangs and technical references remain unchanged. The protected-name set is file-local and case-sensitive: declared/referenced names and standalone identifier string values also protect their prose mentions. This deliberately misses some ordinary prose corrections. Other source languages retain their existing strategy.

Either Python parsing or tokenisation failure skips the whole file; newer syntax unsupported by the running Python version is also skipped. Unsupported encodings are skipped rather than transcoded. The CLI emits `britfix: skipped` diagnostics and separate skipped counts; the hook relays those diagnostics to stderr. These are diagnostic records, not a model-interrupting hook response.

UTF-8 BOMs and line endings survive automatic and interactive file I/O. Markdown, Python and LaTeX protection is verified by byte-preservation tests. JSON retains its existing reserialisation behaviour.

### Bounded LaTeX prose handling

LaTeX uses a balanced lexical scanner, not macro expansion. Command names, optional arguments, unknown macro arguments, mathematics, and verbatim/listings/minted regions are preserved. Mandatory arguments of standard text, heading, caption and footnote commands remain prose; `href` preserves its target but processes its visible text. Unterminated recognised structures preserve the affected remainder and produce `britfix: skipped` diagnostics with a partial-file count.

Custom catcode changes and arbitrary macro expansion are not supported. Unknown macros intentionally sacrifice corrections to preserve their arguments. Escaped braces and comment delimiters are handled before balancing. The tests document the supported command/environment set.
