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


def run_britfix(file_path: str) -> tuple[bool, str]:
    """
    Run britfix on a file.
    Returns (success, output_message).
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
        
        if result.returncode == 0:
            # Check stdout for change info (not stderr!)
            output = result.stdout
            if 'occurrence(s)' in output:
                # Extract changes
                changes = re.findall(r'(\w+) -> (\w+): (\d+) occurrence', output)
                if changes:
                    total = sum(int(c) for _, _, c in changes)
                    details = ', '.join(f"{a}->{b}" for a, b, _ in changes)
                    return True, f"Fixed {total}: {details}"
            return True, ""
        else:
            return False, result.stderr.strip() or result.stdout.strip()
            
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except FileNotFoundError:
        return False, "uv not found"
    except Exception as e:
        return False, str(e)


def process_posttooluse(hook_input: dict) -> dict:
    """Process PostToolUse hook - fixes spelling in files after they're written."""
    tool_name = hook_input.get('tool_name', '')
    tool_input = hook_input.get('tool_input', {})
    
    if tool_name not in ['Write', 'Edit', 'MultiEdit']:
        return hook_input
    
    file_path = tool_input.get('file_path', '')
    if not file_path or not os.path.exists(file_path):
        return hook_input

    # Skip excluded paths entirely (verbatim-content protection — see path_is_excluded)
    if path_is_excluded(file_path, EXCLUDE_PATHS):
        return hook_input

    # Check file extension
    ext = Path(file_path).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return hook_input
    
    # Skip files in the britfix directory itself to avoid recursion
    try:
        if HOOK_DIR in Path(file_path).resolve().parents or Path(file_path).resolve().parent == HOOK_DIR:
            return hook_input
    except:
        pass
    
    success, message = run_britfix(file_path)
    
    if message:
        prefix = "[Britfix]" if success else "[Britfix Error]"
        log(f"{prefix} {Path(file_path).name}: {message}")
    
    return hook_input


def main():
    hook_input = {}
    try:
        hook_input = read_hook_input()
        hook_event = hook_input.get('hook_event_name', '')
        
        if hook_event == 'PostToolUse':
            result = process_posttooluse(hook_input)
        else:
            result = hook_input
        
        print(json.dumps(result))
        return 0
        
    except Exception as e:
        log(f"[Spell Hook] Fatal error: {e}")
        try:
            print(json.dumps(hook_input if hook_input else {}))
        except:
            print("{}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
