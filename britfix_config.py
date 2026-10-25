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
from typing import Optional


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

    The override must be absolute. The hook launches the CLI with its own
    directory as the working directory and the variable inherited unchanged, so
    a relative override could name one file in the hook and another, or none,
    in the CLI it runs.
    """
    override = os.environ.get('BRITFIX_LOCAL_CONFIG')
    if override is not None:
        path = Path(override)
        if not path.is_absolute():
            raise ConfigError(
                f"BRITFIX_LOCAL_CONFIG must be an absolute path (got {override!r})"
            )
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


def matching_exclude_path(file_path: str, exclude_paths) -> Optional[str]:
    """The first configured substring found in file_path's resolved path, or None.

    Compared in forward-slash (posix) form so substrings match cross-platform.
    Matching is naive substring - see the config comment's footgun note. A
    relative path is resolved against the working directory first, which is what
    makes `britfix --input notes/ep.md` and the hook's absolute path agree.
    """
    if not exclude_paths:
        return None
    try:
        resolved = Path(file_path).resolve().as_posix()
    except OSError:
        resolved = Path(file_path).as_posix()
    return next((excl for excl in exclude_paths if excl in resolved), None)


def path_is_excluded(file_path: str, exclude_paths) -> bool:
    """True if file_path's resolved path contains any configured substring."""
    return matching_exclude_path(file_path, exclude_paths) is not None


def user_config_dir() -> Optional[Path]:
    """The user-level britfix directory: the ignore file and config.json live here.

    Windows: %APPDATA%\\britfix. Elsewhere: $XDG_CONFIG_HOME/britfix, or
    ~/.config/britfix when that is unset. None on Windows without APPDATA.

    A relative value is treated as unset, as the XDG Base Directory
    specification asks. The hook runs the CLI with its own directory as the
    working directory, so a relative value would name one file in the hook and
    another in the CLI it runs.
    """
    if os.name == 'nt':
        appdata = os.environ.get('APPDATA', '')
        if appdata and Path(appdata).is_absolute():
            return Path(appdata) / 'britfix'
        return None
    xdg = os.environ.get('XDG_CONFIG_HOME', '')
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / 'britfix'
    try:
        home = Path.home()
    except RuntimeError as e:
        # No HOME and no password-database entry: say so as a config error
        # rather than a traceback from the hook on every edit.
        raise ConfigError(f"Cannot find the user config directory: {e}")
    return home / '.config' / 'britfix'


def user_config_path() -> Optional[Path]:
    """Where the user-level config.json lives, beside the user ignore file.

    It holds exclusions that belong to the person rather than to one checkout
    of britfix, such as other people's code wherever it is cloned. It is read
    by the hook, the CLI and a built binary alike, since none of them bundle it.
    """
    base = user_config_dir()
    return base / 'config.json' if base is not None else None


def merge_local_exclude_paths(config: dict, local_path: Path, label: Optional[str] = None) -> dict:
    """Merge an optional exclusions-only config file into the loaded config.

    Used for the gitignored config.local.json and for the user-level
    config.json. Either file may ONLY extend `exclude_paths` (plus comment
    keys) - its entries are appended to the base list. Other keys are a fatal
    error rather than being silently ignored, `strategies` in particular:
    strategies decide how content is transformed, so they must stay in the
    shared config where they are committed and reviewable, and an override here
    would change output on one machine only.

    `exclude_paths` is the one key that can safely be per-machine. It only ever
    protects more, never less, so it cannot make the two entry points disagree
    about how a file is handled - and since #85 both of them read this file, so
    a private exclusion protects the CLI as well as the hook.

    `label` names the file in error messages; it defaults to the file name,
    which is enough for config.local.json but not for a user-level file that
    shares its name with the shared config.json.
    """
    # A dangling symlink is not absence: it names a file that has gone, and
    # treating it as "no exclusions" would turn every one of them off silently.
    # Opening it below raises, which becomes a ConfigError.
    if not local_path.exists() and not local_path.is_symlink():
        return config

    label = label or local_path.name
    try:
        with open(local_path, encoding='utf-8') as f:
            local = json.load(f)
    except (ValueError, OSError) as e:
        # ValueError covers both json.JSONDecodeError and UnicodeDecodeError,
        # so a file that is not UTF-8 is reported here rather than as a traceback.
        raise ConfigError(f"Cannot read {label}: {e}")

    if not isinstance(local, dict):
        raise ConfigError(f"{label} must be a JSON object")

    unknown = [k for k in local
               if k != 'exclude_paths' and k != 'comment' and not k.endswith('_comment')]
    if unknown:
        raise ConfigError(f"{label} may only set 'exclude_paths' (got {sorted(unknown)})")

    try:
        extra = validate_exclude_paths(local.get('exclude_paths', []))
    except ConfigError as e:
        # Named, because there are now three files an entry can come from.
        raise ConfigError(f"{label}: {e}")

    # .get, not indexing: `exclude_paths` is optional in config.json, as
    # load_exclude_paths already treats it, so a config without the key is a
    # legitimate one with nothing to extend rather than a fault. Indexing raised
    # KeyError here, which is not this function's documented failure type now
    # that it is re-exported and callable from outside.
    config['exclude_paths'] = config.get('exclude_paths', []) + extra
    return config


def merge_user_exclude_paths(config: dict, user_path: Optional[Path]) -> dict:
    """Merge the user-level config.json, by the same rules as config.local.json.

    A missing file, or no user directory at all, leaves the config unchanged.
    Errors name the full path, since 'config.json' alone would point at the
    shared file instead.
    """
    if user_path is None:
        return config
    return merge_local_exclude_paths(config, user_path, label=str(user_path))


def load_exclude_sources(config: dict, local_path: Path, user_path: Optional[Path] = None) -> tuple:
    """Every configured exclusion with the file it came from, as (entry, source).

    In order: config.json, config.local.json, then the user-level config.json.
    The sources are what the CLI names when it skips a file, so a user can find
    the entry responsible without searching three files.
    """
    pairs = [(e, 'config.json') for e in validate_exclude_paths(config.get('exclude_paths', []))]
    local = merge_local_exclude_paths({}, local_path).get('exclude_paths', [])
    pairs += [(e, str(local_path)) for e in local]
    user = merge_user_exclude_paths({}, user_path).get('exclude_paths', [])
    pairs += [(e, str(user_path)) for e in user]
    return tuple(pairs)


def load_exclude_paths(config: dict, local_path: Path, user_path: Optional[Path] = None) -> tuple:
    """The configured exclusions: config.json's, config.local.json's, then the user's."""
    return tuple(entry for entry, _ in load_exclude_sources(config, local_path, user_path))

