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


def test_developer_exclusions_do_not_reach_the_suite(monkeypatch, tmp_path):
    """A personal config.local.json must not change what the suite processes.

    Since #85 the CLI skips a file whose resolved path contains a configured
    substring, and those substrings come from a gitignored config.local.json as
    well as from config.json. An entry as ordinary as '/private/' matches every
    macOS tmp_path, so without the conftest fixture the suite would quietly stop
    correcting its own fixtures on that machine and still report green.
    """
    import britfix_core

    local = tmp_path / 'config.local.json'
    local.write_text('{"exclude_paths": ["/"]}')
    monkeypatch.setattr(britfix_core, '_EXCLUDE_PATHS', None)
    monkeypatch.setenv('BRITFIX_LOCAL_CONFIG', str(local))

    # The loader would now exclude every path there is ...
    assert britfix_core.load_exclude_paths(britfix_core._CONFIG, local) == ('/',)
    # ... and the suite still sees none of it.
    assert britfix_core.get_exclude_paths() == ()


def test_subprocess_runs_ignore_the_developer_config(tmp_path):
    """The half of the isolation that patching cannot provide.

    Several tests run britfix.py as a subprocess, which re-reads the config from
    disk in a new process. Only the environment variable reaches those, so it is
    what stops a personal config.local.json from deciding whether they pass.
    """
    assert os.environ['BRITFIX_LOCAL_CONFIG']
    assert not Path(os.environ['BRITFIX_LOCAL_CONFIG']).exists()

    probe = tmp_path / 'probe.md'
    probe.write_text('The color.\n')
    result = subprocess.run(
        [sys.executable, 'britfix.py', '--input', str(probe), '--no-backup', '--quiet'],
        cwd=Path(__file__).parent, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert probe.read_text() == 'The colour.\n', result.stdout + result.stderr


def test_unset_xdg_uses_isolated_home(monkeypatch):
    from britfix_core import get_user_ignore_path

    monkeypatch.setattr(os, 'name', 'posix')
    monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
    assert get_user_ignore_path() == Path.home() / '.config' / 'britfix' / 'ignore'
    assert not get_user_ignore_path().exists()
