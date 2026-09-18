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

### Markdown File Handling

Markdown prose is corrected; code spans, fenced and indented code blocks, and blockquotes are left alone.

- **URLs**: bare HTTP(S) URLs, including query strings, fragments and balanced parentheses, are preserved. Apostrophes inside a URL remain URI data. URLs without a scheme (`www.example.org`) are not recognised.
- **Links and references**: inline and image destinations are preserved, as are reference identifiers at both the use site and the definition; collapsed and shortcut labels stay unchanged where the visible text also identifies the reference. Ordinary link text and surrounding prose still convert. A reference definition keeps its label, destination and title verbatim; a line that only looks like one (for example `[Note]: some sentence` with trailing words) is treated as prose.
- **Footnotes**: the footnote label (`[^note]`) is kept at its definition and use sites, but the footnote text itself is corrected.
- **HTML**: tags and their attributes, HTML comments, and `<script>`/`<style>` bodies are preserved. Text inside HTML comments is kept verbatim; this is a deliberate change, as earlier versions corrected comment text. Markup written inside code is not treated as markup. An HTML comment, `<script>` or `<style>` that starts at the beginning of a line runs to its closing marker, even across blank lines. One that is never closed, or that starts mid-line and is not closed within its paragraph, is protected only to the end of that paragraph (or to the next code fence or backtick), so correction resumes afterwards instead of stopping for the rest of the file.
- **Quotations**: an emphasised quotation is preserved verbatim, so `*"color"*`, `_“color”_` and the bold forms `**"color"**` and `__"color"__` keep their spelling. The delimiters must flank the quotation the way emphasis does, so a delimiter belonging to a path or a glob (`"src/*"` next to `"**/test"`) does not open one, and a run of asterisks only pairs with a run of the same length. A quotation nested in further emphasis (`_*"color"*_`) keeps its protection. Ordinary emphasis without quotation marks still converts, and quotations inside code spans, code blocks and blockquotes are not scanned at all. Setting `strategies.markdown.preserve_quoted_prose` to `true` in `config.json` (boolean, default `false`) preserves every quoted run of prose rather than only the emphasised ones; a value that is not a boolean is a fatal config error, as for `exclude_paths`. That opt-in mode is deliberately blunt: an unclosed double or curly-double quotation mark, an inch mark such as `5"` among them, preserves the rest of its paragraph, so spellings after it are left alone. Straight single quotes need a pair, so apostrophes, elisions (`'cause`, `‘Tis`), decades (`'90s`) and possessives still convert in both modes.

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

### Python and file preservation

Python files use tokenisation and AST docstring identification while retaining the `code:` ignore namespace. Non-docstring string literals, executable tokens, shebangs and technical references (backticks, dotted names such as `xref.finalize`, URLs and quotations) remain unchanged. Tokenisation and AST analysis, the file-local identifier set, docstring parameter labels and failing closed on unparseable source are specific to Python; see [Code File Handling](#code-file-handling) for the protections that apply to source files generally.

Docstring parameter labels are preserved, and only the label: the description beside it is still corrected, so documented prose does not stop being processed. The forms recognised are:

- Google style at the start of a line. The untyped forms `color:` and `color : bool` are recognised anywhere in a docstring. The typed forms `color (bool):`, `color (bool, optional):`, `*args (tuple):` and `**kwargs (dict):` are recognised only inside a section block, meaning the indented body under an `Args:`, `Arguments:`, `Keyword Args:`, `Attributes:`, `Parameters:`, `Other Parameters:`, `Returns:`, `Yields:`, `Raises:`, `Receives:` or `Warns:` heading, because `Deprecated (since the 2.0 release):` is a sentence rather than a label. The name and the parenthesised type are preserved; the description after the colon is not. A line whose first word is followed by a space rather than a colon is ordinary prose, so `See also: the color table` is still corrected.
- Sphinx info fields that carry a name: `:param`, `:parameter`, `:arg`, `:argument`, `:key`, `:keyword`, `:kwarg`, `:var`, `:ivar`, `:cvar`, `:raises`, `:raise`, `:except` and `:exception`. The field name and the name it carries are preserved, so `:raises ValueError: bad color` keeps the class name and still corrects the description. `:returns:` and any unrecognised field are ordinary prose.
- `:type`, `:vartype` and `:rtype` preserve the whole line, because their payload is a type expression rather than a description.
- NumPy name lines inside a section whose heading carries a dashed underline (`Parameters`, `Other Parameters`, `Attributes`, `Returns`, `Yields`, `Raises`, `Receives`, `Warns`). A line at the heading's own indent that is wholly names, optionally starred and optionally followed by ` : type`, is preserved, but only when a more deeply indented description follows it, which is what the format requires; a run of prose at the section's own indent is therefore not mistaken for names. The description itself is still corrected. A section ends at the next underlined heading, whatever it is called, so an underlined `Notes` closes the section before it and its own body is ordinary prose. A heading with no underline neither opens a section nor closes one.

A name recognised as a parameter label is protected file-wide: it is left alone everywhere else in that file's comments and docstrings, not only in the docstring that documents it, so a description such as `Alias for color` keeps the name it refers to. Only labels that a section documents count here, that is a Google label inside a section block, a Sphinx info field, or a NumPy name line; a sentence that merely begins with a word and a colon is still protected where it stands but records no name. Matching is case-sensitive, as it is for identifiers, so documenting `Color:` does not protect `color`.

Labels are matched per line, and a bare carriage return does not start a line, so in a file whose only line ending is `\r` only the first line of each docstring is scanned for them.

Words that name a Python identifier are also left alone in comments and docstrings. Matching is file-local and case-sensitive, and is controlled by `strategies.code.python_identifier_protection` in `config.json`:

- `"defined"` (default): only names the file itself defines protect their prose mentions. That covers function and class names; parameters, including `*args`, `**kwargs`, keyword-only and lambda parameters; assignment, `for`, `with ... as`, `except ... as`, comprehension, walrus and `match` capture targets; attributes assigned in the file (`self.color = ...`); `global` and `nonlocal` names; import bindings (the `as` name, or the first segment of `import a.b`); and type parameters and aliases. Names that are only used, such as a library keyword argument (`ax.plot(color="red")`) or an attribute that is read or called, protect nothing, so `# Pick a color` in that file still becomes `# Pick a colour`.
- `"all"`: every name token anywhere in the file protects its prose mentions. This misses more ordinary corrections.

In both modes, a non-docstring string literal whose whole value is an identifier (such as `"color"`) also protects its prose mentions. Any other value for the setting is a fatal config error.

Either Python parsing or tokenisation failure skips the whole file, so it receives no corrections at all; newer syntax unsupported by the running Python version is also skipped. If the positions reported by the tokeniser or parser ever disagree with the file text, the file is skipped rather than written. Files whose only line ending is a bare carriage return (`\r`) tokenise as a single line, so only a comment that opens the file is corrected; later comments are left unchanged (docstrings are still corrected under the default setting). Unsupported encodings are skipped rather than transcoded. The CLI emits `britfix: skipped` diagnostics and separate skipped counts; the hook relays those diagnostics to stderr. These are diagnostic records, not a model-interrupting hook response.

UTF-8 BOMs and line endings survive automatic and interactive file I/O. Markdown, Python and LaTeX protection is verified by byte-preservation tests. JSON retains its existing reserialisation behaviour.

### Bounded LaTeX prose handling

LaTeX uses a balanced lexical scanner, not macro expansion. Command names, optional arguments, unknown macro arguments, mathematics, and verbatim/listings/minted regions are preserved. Mandatory arguments of standard text, heading, caption and footnote commands remain prose; `href` preserves its target but processes its visible text. Unterminated recognised structures preserve the affected remainder and produce `britfix: skipped` diagnostics with a partial-file count: an unclosed `$`, verbatim region, environment or command argument pauses correction to the end of the file. The argument of `\url`, `\path`, `\nolinkurl`, the target of `\href` and brace-delimited `\lstinline`/`\mintinline` code are read verbatim, so `%` and `\` inside them do not start a comment or escape.

Custom catcode changes and arbitrary macro expansion are not supported. Unknown macros intentionally sacrifice corrections to preserve their arguments, so prose inside macros such as `\enquote`, `\todo`, `\textsc` or `\item[...]` labels is deliberately left alone. Escaped braces and comment delimiters are handled before balancing. The tests document the supported command/environment set.

Quoted prose in LaTeX is corrected by default. To preserve it, set `strategies.latex.preserve_quoted_prose` to `true` in `config.json` (boolean, default `false`; a non-boolean value is a fatal config error). This is separate from the Markdown setting because a straight `"` in LaTeX is often an inch mark or a babel shorthand rather than a quotation.

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
