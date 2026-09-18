"""Keep the test suite independent of the developer's personal ignores."""

from pathlib import Path

import pytest

import britfix_core


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
    """
    monkeypatch.setenv('BRITFIX_LOCAL_CONFIG', str(tmp_path / 'no-config.local.json'))
    monkeypatch.setattr(britfix_core, 'get_exclude_paths', lambda: ())
