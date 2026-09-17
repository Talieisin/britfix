"""Exercise conftest under a polluted parent environment, in a fresh pytest."""

import os
from pathlib import Path
import subprocess
import sys


def test_suite_does_not_inherit_user_ignores(tmp_path):
    config = tmp_path / 'external-config'
    (config / 'britfix').mkdir(parents=True)
    (config / 'britfix' / 'ignore').write_text('program\ncolor\n')
    env = dict(os.environ, XDG_CONFIG_HOME=str(config), APPDATA=str(config))
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q',
         'test_britfix.py::TestPhraseIntegration::test_end_to_end_phrase_in_britfixignore',
         'test_britfix.py::TestUserIgnorePath'],
        cwd=Path(__file__).parent, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_unset_xdg_uses_isolated_home(monkeypatch):
    from britfix_core import get_user_ignore_path

    monkeypatch.setattr(os, 'name', 'posix')
    monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
    assert get_user_ignore_path() == Path.home() / '.config' / 'britfix' / 'ignore'
    assert not get_user_ignore_path().exists()
