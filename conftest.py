"""Keep the test suite independent of the developer's personal ignores."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

import britfix_core


_SESSION_ENV = ('HOME', 'XDG_CONFIG_HOME', 'APPDATA', 'BRITFIX_LOCAL_CONFIG')
_saved_env = {}
_session_home = None


def pytest_configure(config):
    """Isolate the user config before any test module is imported.

    The fixtures below only start with the first test, but test_britfix_hook
    imports britfix_hook at collection, and the hook loads every exclusion
    file at import: config.local.json and the user-level config.json. An
    invalid personal file made it exit there, which aborted the whole run
    before a single fixture had applied. So the session starts from an empty
    home and an inert local config too; the fixtures still give each test its
    own.
    """
    global _session_home
    _session_home = Path(tempfile.mkdtemp(prefix='britfix-test-home-'))
    inert = _session_home / 'inert-config.local.json'
    inert.write_text('{}', encoding='utf-8')
    values = {
        'HOME': str(_session_home),
        'XDG_CONFIG_HOME': str(_session_home / '.config'),
        'APPDATA': str(_session_home / 'AppData'),
        'BRITFIX_LOCAL_CONFIG': str(inert),
    }
    for name in _SESSION_ENV:
        _saved_env[name] = os.environ.get(name)
        os.environ[name] = values[name]


def pytest_unconfigure(config):
    for name, value in _saved_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    if _session_home is not None:
        shutil.rmtree(_session_home, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_user_config(monkeypatch, tmp_path):
    """Tests can override these defaults when exercising config discovery."""
    home = tmp_path / 'isolated-user-home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home / '.config'))
    monkeypatch.setenv('APPDATA', str(home / 'AppData'))


@pytest.fixture(autouse=True)
def isolated_path_exclusions(monkeypatch, tmp_path):
    """Ignore the developer's own config.local.json, which the CLI now reads.

    Since #85 the CLI skips a file whose resolved path contains a configured
    substring, and exclusions come from a gitignored config.local.json as well
    as from config.json. A developer entry as ordinary as '/private/' matches
    every macOS tmp_path, so without this the suite would stop processing its
    own fixtures on that machine.

    Both halves are needed. The environment variable is the one that reaches the
    tests which run britfix.py as a subprocess, where patching this process
    changes nothing; the attribute patch covers the in-process callers and is
    what tests exercising exclusions override with what they need.

    The variable names an empty but real config, not a missing one: a missing
    one is a fatal error, so that britfix cannot be silently disabled by a stray
    variable in someone's environment.
    """
    inert = tmp_path / 'inert-config.local.json'
    inert.write_text('{}', encoding='utf-8')
    monkeypatch.setenv('BRITFIX_LOCAL_CONFIG', str(inert))
    monkeypatch.setattr(britfix_core, 'get_exclude_paths', lambda: ())
