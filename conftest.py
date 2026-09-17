"""Keep the test suite independent of the developer's personal ignores."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_user_config(monkeypatch, tmp_path):
    """Tests can override these defaults when exercising config discovery."""
    home = tmp_path / 'isolated-user-home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home / '.config'))
    monkeypatch.setenv('APPDATA', str(home / 'AppData'))
