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

# Load supported extensions from config
def load_supported_extensions():
    """Load supported extensions from config.json."""
    extensions = set()

    config_path = HOOK_DIR / 'config.json'
    if config_path.exists():
        try:
            with open(config_path) as f:
                data = json.load(f)
                strategies = data.get('strategies', {})
                for strategy_config in strategies.values():
                    extensions.update(strategy_config.get('extensions', []))
        except:
            pass

    # Fallback defaults if config is empty
    if not extensions:
        extensions = {'.md', '.txt', '.tex', '.html', '.htm', '.xml', '.json',
                      '.py', '.js', '.ts', '.jsx', '.tsx'}

    return extensions

SUPPORTED_EXTENSIONS = load_supported_extensions()


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
    try:
        hook_input = json.load(sys.stdin)
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
            print(json.dumps(hook_input))
        except:
            print("{}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
