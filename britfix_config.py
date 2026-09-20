"""Configuration policy shared by both entry points.

This module exists to be importable by britfix_hook.py, which must not import
britfix_core: the core loads and validates config.json at import and exits the
process when it refuses it, and the hook runs on every edit the user makes. A
config the hook tolerates but the core rejects used to leave the hook working
(it reports nothing and the edit completes); importing the core would turn that
into a failed hook on every edit, and would replace the hook's own diagnostics,
which carry a prefix and go through its log file.

So everything here raises ConfigError and does no work at import. britfix_core
re-exports these names, so `from britfix_core import ...` keeps working, and the
hook and the CLI apply one and the same rule rather than two copies of it.
"""
import json
import os
from pathlib import Path


class ConfigError(Exception):
    """Raised when config.json is missing or invalid."""
    pass


# --- Path exclusions (exclude_paths) ---------------------------------------
#
# The tool's verbatim-content protection: a file whose resolved path contains a
# configured substring is left uncorrected. This lived only in britfix_hook.py,
# so a file was protected when Claude Code edited it through the hook and
# unprotected the moment anything pointed the CLI at it (issue #85). That is the
# same shape of defect as the extension allowlist in #75, and it is fixed the
# same way: the policy lives in one place and both entry points consult it.
#
# The messages below are the wording the hook printed before the move, so its
# stderr did not change. Each entry point reports them in its own voice: the
# hook logs "[Britfix Error] ..." and exits 1, the CLI prints "Britfix config
# error: ..." and exits 1.


def local_config_path() -> Path:
    """Where config.local.json lives.

    Beside config.json and resolved the same way, from this module's own
    directory rather than the working directory, so the CLI honours the same
    exclusions wherever it is run from. `just build` bundles config.json but not
    the local file, so a frozen binary sees committed exclusions only; the hook
    runs the source tree, so the hook's own CLI path is covered.

    BRITFIX_LOCAL_CONFIG overrides the location, for the test suite: several of
    its tests run britfix.py as a subprocess, where patching cannot reach, and a
    developer exclusion as ordinary as '/private/' matches every macOS temp
    directory. An override naming a path that does not exist is a fatal error
    rather than a quiet no-op: silently turning every private exclusion off, on
    both entry points, because of one stray variable is exactly the failure this
    setting exists to prevent. Absence of the default file is still fine, since
    that is the normal state and not an instruction.
    """
    override = os.environ.get('BRITFIX_LOCAL_CONFIG')
    if override is not None:
        path = Path(override)
        if not path.exists():
            raise ConfigError(
                f"BRITFIX_LOCAL_CONFIG points at {path}, which does not exist"
            )
        return path
    return Path(os.path.dirname(os.path.abspath(__file__))) / 'config.local.json'


def validate_exclude_paths(raw) -> list:
    """Validate an `exclude_paths` value: must be a list of non-empty strings.

    Invalid config is fatal to the caller (like a missing 'strategies' object):
    silently dropping entries would process files the user asked to protect, and
    an empty-string entry matches every path, silently disabling britfix
    everywhere.
    """
    if not isinstance(raw, list):
        raise ConfigError(f"'exclude_paths' must be a list (got {type(raw).__name__})")
    for entry in raw:
        if not isinstance(entry, str) or not entry:
            raise ConfigError(f"'exclude_paths' entries must be non-empty strings (got {entry!r})")
    return raw


def path_is_excluded(file_path: str, exclude_paths) -> bool:
    """True if file_path's resolved path contains any configured substring.

    Compared in forward-slash (posix) form so substrings match cross-platform.
    Matching is naive substring - see the config comment's footgun note. A
    relative path is resolved against the working directory first, which is what
    makes `britfix --input notes/ep.md` and the hook's absolute path agree.
    """
    if not exclude_paths:
        return False
    try:
        resolved = Path(file_path).resolve().as_posix()
    except OSError:
        resolved = Path(file_path).as_posix()
    return any(excl in resolved for excl in exclude_paths)


def merge_local_exclude_paths(config: dict, local_path: Path) -> dict:
    """Merge an optional, gitignored config.local.json into the loaded config.

    The local file may ONLY extend `exclude_paths` (plus comment keys) - its
    entries are appended to the base list. Other keys are a fatal error rather
    than being silently ignored, `strategies` in particular: strategies decide
    how content is transformed, so they must stay in the shared config where
    they are committed and reviewable, and an override here would change output
    on one machine only.

    `exclude_paths` is the one key that can safely be per-machine. It only ever
    protects more, never less, so it cannot make the two entry points disagree
    about how a file is handled - and since #85 both of them read this file, so
    a private exclusion protects the CLI as well as the hook.
    """
    if not local_path.exists():
        return config

    try:
        with open(local_path) as f:
            local = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ConfigError(f"Cannot read {local_path.name}: {e}")

    if not isinstance(local, dict):
        raise ConfigError(f"{local_path.name} must be a JSON object")

    unknown = [k for k in local
               if k != 'exclude_paths' and k != 'comment' and not k.endswith('_comment')]
    if unknown:
        raise ConfigError(f"{local_path.name} may only set 'exclude_paths' (got {sorted(unknown)})")

    config['exclude_paths'] = config['exclude_paths'] + validate_exclude_paths(local.get('exclude_paths', []))
    return config


def load_exclude_paths(config: dict, local_path: Path) -> tuple:
    """The configured exclusions: config.json's list plus config.local.json's."""
    merged = dict(config)
    merged['exclude_paths'] = validate_exclude_paths(config.get('exclude_paths', []))
    return tuple(merge_local_exclude_paths(merged, local_path)['exclude_paths'])
