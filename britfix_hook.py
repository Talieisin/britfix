#!/usr/bin/env python3
"""
Britfix hook - converts US spellings to British.
Processes files after they're written (PostToolUse).
"""
import json
import sys
import os
import subprocess
import re
import difflib
from pathlib import Path
from datetime import datetime

# Directory where this hook lives
HOOK_DIR = Path(__file__).parent.resolve()

# Optional log file - set BRITFIX_LOG env var to enable
LOG_FILE = os.getenv('BRITFIX_LOG', '')

def log(message: str):
    """Log to stderr and optionally to file."""
    print(message, file=sys.stderr)
    if LOG_FILE:
        try:
            with open(LOG_FILE, 'a') as f:
                f.write(f"{datetime.now().isoformat()} {message}\n")
        except:
            pass

def validate_exclude_paths(raw) -> list:
    """Validate the `exclude_paths` config value: must be a list of non-empty strings.
    Invalid config is fatal (like a missing 'strategies' object): silently dropping
    entries would process files the user asked to protect, and an empty-string
    entry matches every path, silently disabling britfix everywhere."""
    if not isinstance(raw, list):
        log(f"[Britfix Error] 'exclude_paths' must be a list (got {type(raw).__name__})")
        sys.exit(1)
    for entry in raw:
        if not isinstance(entry, str) or not entry:
            log(f"[Britfix Error] 'exclude_paths' entries must be non-empty strings (got {entry!r})")
            sys.exit(1)
    return raw


def path_is_excluded(file_path: str, exclude_paths: list) -> bool:
    """True if file_path's resolved path contains any configured substring.
    Compared in forward-slash (posix) form so substrings match cross-platform.
    Matching is naive substring — see the config comment's footgun note."""
    if not exclude_paths:
        return False
    try:
        resolved = Path(file_path).resolve().as_posix()
    except OSError:
        resolved = Path(file_path).as_posix()
    return any(excl in resolved for excl in exclude_paths)


def merge_local_config(config: dict, local_path: Path) -> dict:
    """Merge an optional, gitignored config.local.json into the loaded config.

    The local file may ONLY extend `exclude_paths` (plus comment keys) — its
    entries are appended to the base list. Other keys are a fatal error rather
    than being silently ignored: in particular `strategies` must stay in the
    shared config, because the CLI loads config.json independently and a
    hook-only override would desync the two."""
    if not local_path.exists():
        return config

    try:
        with open(local_path) as f:
            local = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log(f"[Britfix Error] Cannot read {local_path.name}: {e}")
        sys.exit(1)

    if not isinstance(local, dict):
        log(f"[Britfix Error] {local_path.name} must be a JSON object")
        sys.exit(1)

    unknown = [k for k in local
               if k != 'exclude_paths' and k != 'comment' and not k.endswith('_comment')]
    if unknown:
        log(f"[Britfix Error] {local_path.name} may only set 'exclude_paths' (got {sorted(unknown)})")
        sys.exit(1)

    config['exclude_paths'] = config['exclude_paths'] + validate_exclude_paths(local.get('exclude_paths', []))
    return config


# Load and validate config
def load_config():
    """Load and validate config.json (plus optional config.local.json). Exits if invalid."""
    config_path = HOOK_DIR / 'config.json'

    if not config_path.exists():
        log(f"[Britfix Error] Config file not found: {config_path}")
        sys.exit(1)

    try:
        with open(config_path) as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        log(f"[Britfix Error] Invalid JSON in config: {e}")
        sys.exit(1)

    if 'strategies' not in config or not isinstance(config['strategies'], dict):
        log("[Britfix Error] Config missing 'strategies' object")
        sys.exit(1)

    config['exclude_paths'] = validate_exclude_paths(config.get('exclude_paths', []))
    config = merge_local_config(config, HOOK_DIR / 'config.local.json')

    return config


def load_supported_extensions(config: dict) -> set:
    """Extract all supported extensions from config."""
    extensions = set()
    for strategy_config in config['strategies'].values():
        if 'extensions' in strategy_config:
            extensions.update(strategy_config['extensions'])
    return extensions


_CONFIG = load_config()
SUPPORTED_EXTENSIONS = load_supported_extensions(_CONFIG)
EXCLUDE_PATHS = _CONFIG.get('exclude_paths', [])


def read_hook_input(stream=sys.stdin) -> dict:
    """
    Read a single JSON payload from stdin without waiting for EOF.
    Claude keeps the pipe open in some cases (cancels/timeouts), so we need to
    stop reading as soon as one well-formed object has been received.
    """
    decoder = json.JSONDecoder()
    buffer = ""
    encoding = getattr(stream, "encoding", "utf-8") or "utf-8"
    binary_stream = getattr(stream, "buffer", None)

    if binary_stream is not None:
        read_fn = getattr(binary_stream, "read1", None) or binary_stream.read

        def _read_chunk():
            chunk = read_fn(4096)
            return chunk.decode(encoding, errors="replace") if chunk else ""
    else:
        def _read_chunk():
            return stream.read(4096)

    while True:
        chunk = _read_chunk()
        if not chunk:
            if buffer.strip():
                raise json.JSONDecodeError("Incomplete JSON input", buffer, len(buffer))
            return {}

        buffer += chunk
        buffer = buffer.lstrip()
        if not buffer:
            continue

        try:
            hook_input, _ = decoder.raw_decode(buffer)
            return hook_input
        except json.JSONDecodeError:
            # Need more data - keep reading
            continue


def run_britfix(file_path: str) -> tuple[bool, str, list]:
    """
    Run britfix on a file.
    Returns (success, error_message, skipped_notes).

    What changed is NOT read from the CLI's stdout. That stdout prints each word
    twice, once in the per-file block and once in the totals block, so the old
    regex over the whole output reported double the real count. It is also prose
    written for humans, so any rewording of it silently changes the hook's
    report. The caller diffs the file itself instead — see summarise_changes.
    """
    cmd = ['uv', 'run', '--directory', str(HOOK_DIR),
           'python', 'britfix.py', '--input', file_path, '--no-backup']

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=HOOK_DIR
        )

        skipped = []
        for line in result.stderr.splitlines():
            if line.startswith('britfix: skipped '):
                log(line)
                skipped.append(line)
        if result.returncode == 0:
            return True, "", skipped
        return False, (result.stderr.strip() or result.stdout.strip()), skipped

    except subprocess.TimeoutExpired:
        return False, "Timeout", []
    except FileNotFoundError:
        return False, "uv not found", []
    except Exception as e:
        return False, str(e), []


# --- Change reporting ------------------------------------------------------
#
# A rewrite must be visible. Hook stderr on exit 0 reaches only the debug log
# (never the transcript, and never Claude), so the report is carried by the
# documented PostToolUse JSON output instead: top-level `systemMessage` for the
# user, `hookSpecificOutput.additionalContext` for the model that made the edit.
# Both are emitted only when the file's bytes actually changed, so an ordinary
# edit that needed no correction stays silent.

# How many individual word changes to name before summarising the rest.
MAX_REPORTED_CHANGES = 5

# Defensive ceiling per emitted string. Claude Code caps hook output strings at
# 10,000 characters and replaces anything longer with a preview plus a file
# path, which would stop the JSON parsing; stay far below that.
MAX_MESSAGE_CHARS = 1500

# Letters / digits / underscores / everything else, so a substitution pairs up
# word-for-word rather than smearing across the punctuation around it.
_TOKEN_RE = re.compile(r"[^\W\d_]+|\W+|\d+|_+", re.UNICODE)

def is_correction_shaped(token: str) -> bool:
    """True if a token could be one side of a spelling correction: letters,
    possibly with hyphens, and at least one letter.

    Hyphens are allowed because the dictionary's prefix entries rewrite across
    one. `feto-` maps to `foeto` with no trailing hyphen, so `feto-scan` becomes
    `foetoscan`: a real correction whose two sides are not plain words. Four
    entries need that today (estr-, feto-, leuk-, paleo-), but the reason to
    allow it is that the dictionary can grow another awkward one, and that the
    cost of rejecting a legitimate pair is high: the check below collapses the
    whole file's report, so one unrecognised pair would take down a report of
    nine perfectly explainable corrections alongside it."""
    return (bool(token)
            and all(char == '-' or char.isalpha() for char in token)
            and any(char.isalpha() for char in token))


def read_file_bytes(path: str):
    """Read a file as bytes, or None if it cannot be read.

    None means 'cannot tell', never 'empty': the file may have been deleted or
    replaced between the edit and the hook, and that must not raise."""
    try:
        with open(path, 'rb') as f:
            return f.read()
    except OSError:
        return None


def pair_line_changes(before_line: str, after_line: str) -> list:
    """Pair up the words a single line replaced: [(before, after), ...]."""
    before_tokens = _TOKEN_RE.findall(before_line)
    after_tokens = _TOKEN_RE.findall(after_line)
    pairs = []
    matcher = difflib.SequenceMatcher(None, before_tokens, after_tokens, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'replace':
            continue
        if (i2 - i1) == (j2 - j1):
            for offset in range(i2 - i1):
                pairs.append((before_tokens[i1 + offset], after_tokens[j1 + offset]))
        else:
            # Uneven replacement: report the whole span rather than mispair it.
            pairs.append((''.join(before_tokens[i1:i2]), ''.join(after_tokens[j1:j2])))
    return pairs


def summarise_changes(before, after) -> dict:
    """Describe what britfix did to a file, from the file itself.

    Returns {'changed': bool, 'detailed': bool, 'total': int, 'items': [...]},
    where items are (line_number, before_word, after_word) triples.

    'detailed' is False when the change is real but cannot be described safely
    (unreadable file, or a differing line count, which an in-place word
    substitution never produces and a truncated write does). The report then
    says a change happened without inventing a count."""
    empty = {'changed': False, 'detailed': False, 'total': 0, 'items': []}
    if before is None or after is None or before == after:
        return empty

    try:
        before_lines = before.decode('utf-8', errors='replace').splitlines()
        after_lines = after.decode('utf-8', errors='replace').splitlines()
    except Exception:
        return {'changed': True, 'detailed': False, 'total': 0, 'items': []}

    if len(before_lines) != len(after_lines):
        return {'changed': True, 'detailed': False, 'total': 0, 'items': []}

    items = []
    for index, (before_line, after_line) in enumerate(zip(before_lines, after_lines), start=1):
        if before_line == after_line:
            continue
        for old, new in pair_line_changes(before_line, after_line):
            items.append((index, old, new))

    if not items:
        # Bytes differ but no line-level word change: a BOM or line-ending
        # difference. Real, but not a spelling report.
        return {'changed': True, 'detailed': False, 'total': 0, 'items': []}

    if any(not (is_correction_shaped(old) and is_correction_shaped(new))
           for _, old, new in items):
        # A spelling correction replaces one word with another word. Anything
        # else means the file changed in a way britfix cannot account for, most
        # likely because something else wrote to it during the run: the
        # before-read and the after-read straddle the corrector, so that window
        # exists. Say less rather than attributing a foreign edit to britfix and
        # naming words it never touched.
        return {'changed': True, 'detailed': False, 'total': 0, 'items': []}

    return {'changed': True, 'detailed': True, 'total': len(items), 'items': items}


def format_change_list(items: list, limit: int = MAX_REPORTED_CHANGES) -> str:
    """Render change triples as 'L12 color->colour, L40 center->centre, +3 more'."""
    shown = [f"L{line} {old}->{new}" for line, old, new in items[:limit]]
    remainder = len(items) - len(shown)
    if remainder > 0:
        shown.append(f"+{remainder} more")
    return ', '.join(shown)


def describe_skips(skipped_notes: list) -> str:
    """One short clause naming why britfix declined to correct part of a file."""
    reasons = []
    for note in skipped_notes:
        detail = note[len('britfix: skipped '):].strip()
        try:
            parsed = json.loads(detail)
            reason = parsed.get('reason', '') or detail
            region = parsed.get('region', '')
            reasons.append(f"{region}: {reason}" if region else str(reason))
        except (ValueError, AttributeError):
            reasons.append(detail)
    unique = []
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    return '; '.join(unique[:MAX_REPORTED_CHANGES])


def truncate(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    return text if len(text) <= limit else text[:limit - 3] + '...'


def build_hook_output(file_path: str, summary: dict, error: str, skipped_notes: list) -> dict:
    """Build the PostToolUse JSON output describing what happened to file_path.

    Returns {} when there is nothing worth saying, which is the common case."""
    user_parts = []
    model_parts = []

    # Bound the variable-length parts here rather than truncating the finished
    # sentence, so an unusually long path can never cut off the tail of the
    # message to the model, which is where "must not be reverted" lives.
    file_path = truncate(str(file_path), 300)

    if summary.get('changed'):
        if summary.get('detailed'):
            count = summary['total']
            noun = 'spelling' if count == 1 else 'spellings'
            detail = truncate(format_change_list(summary['items']), 400)
            user_parts.append(f"britfix rewrote {count} {noun} in {file_path}: {detail}")
            model_parts.append(
                f"The britfix PostToolUse hook rewrote {count} US {noun} in {file_path} "
                f"after this edit ({detail}), so the file on disk now differs from the text "
                f"that was written. This rewrite is deliberate and must not be reverted; if a "
                f"rewritten token has to keep its US spelling, add it to .britfixignore at the "
                f"repository root as a quoted phrase, such as \"w:color\"."
            )
        else:
            # Deliberately weaker wording. Here the hook knows the file changed
            # but not that britfix is what changed it, so it claims neither.
            user_parts.append(
                f"{file_path} changed after the edit; britfix could not summarise the change")
            model_parts.append(
                f"The file {file_path} on disk differs from the text that was written. The "
                f"britfix PostToolUse hook ran on it but could not summarise the difference, so "
                f"which part of it is a spelling correction is not established. Re-read the file "
                f"before editing it further."
            )

    if skipped_notes:
        # Worth telling the model even when nothing changed: it explains why the
        # US spellings it wrote are still there.
        model_parts.append(
            f"britfix skipped correcting part or all of {file_path} "
            f"({describe_skips(skipped_notes)}), so spellings there are unchanged."
        )

    if error:
        user_parts.append(f"britfix hook failed on {file_path}: {error}")

    output = {}
    if user_parts:
        output['systemMessage'] = truncate('; '.join(user_parts))
    if model_parts:
        output['hookSpecificOutput'] = {
            'hookEventName': 'PostToolUse',
            'additionalContext': truncate(' '.join(model_parts)),
        }
    return output


def process_posttooluse(hook_input: dict) -> dict:
    """Process PostToolUse hook - fixes spelling in files after they're written.

    Returns the hook's JSON output: {} when there is nothing to report."""
    tool_name = hook_input.get('tool_name', '')
    tool_input = hook_input.get('tool_input', {})

    if tool_name not in ['Write', 'Edit', 'MultiEdit']:
        return {}

    file_path = tool_input.get('file_path', '')
    if not file_path or not os.path.exists(file_path):
        return {}

    # Skip excluded paths entirely (verbatim-content protection — see path_is_excluded)
    if path_is_excluded(file_path, EXCLUDE_PATHS):
        return {}

    # Check file extension
    ext = Path(file_path).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return {}

    # Skip files in the britfix directory itself to avoid recursion
    try:
        if HOOK_DIR in Path(file_path).resolve().parents or Path(file_path).resolve().parent == HOOK_DIR:
            return {}
    except:
        pass

    # Read before and after so the report describes what actually happened to
    # the bytes on disk, independently of anything the CLI prints.
    before = read_file_bytes(file_path)
    success, error, skipped_notes = run_britfix(file_path)
    after = read_file_bytes(file_path)

    # Reporting must never be able to fail an edit: degrade to no report.
    try:
        summary = summarise_changes(before, after)
        output = build_hook_output(file_path, summary, '' if success else error, skipped_notes)
    except Exception as e:
        log(f"[Britfix Error] Could not summarise changes for {file_path}: {e}")
        return {}

    if 'systemMessage' in output:
        prefix = "[Britfix]" if success else "[Britfix Error]"
        log(f"{prefix} {output['systemMessage']}")

    return output


def main():
    """Always print one JSON object and always exit 0.

    Stdout carries only the hook's own output fields. It deliberately no longer
    echoes the input payload back: the documented contract is that stdout
    "must contain only the JSON object", and an echoed payload includes
    tool_input.content, which for a large Write pushes stdout past the 10,000
    character output cap. Past that cap the text is replaced by a preview and a
    file path, which is not parseable JSON, so the echo destroyed the very
    report it was carrying on exactly the largest files."""
    try:
        hook_input = read_hook_input()
        hook_event = hook_input.get('hook_event_name', '')

        result = process_posttooluse(hook_input) if hook_event == 'PostToolUse' else {}

        try:
            payload = json.dumps(result)
        except Exception:
            payload = "{}"
        print(payload)
        return 0

    except Exception as e:
        log(f"[Spell Hook] Fatal error: {e}")
        print("{}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
