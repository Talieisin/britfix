#!/usr/bin/env python3
"""Tests for britfix_hook — exclude_paths validation and path-based skipping."""
import json
import pytest
import britfix_hook as h


# --- validate_exclude_paths (config validation) ----------------------------

def test_validate_exclude_paths_valid_list():
    assert h.validate_exclude_paths(['/Transcripts/', '/quotes/']) == ['/Transcripts/', '/quotes/']


def test_validate_exclude_paths_empty():
    assert h.validate_exclude_paths([]) == []


def test_validate_exclude_paths_not_a_list_is_fatal():
    # A bare string must NOT be silently ignored: the user asked for protection,
    # so a config mistake must stop the hook, not process the protected files.
    with pytest.raises(SystemExit):
        h.validate_exclude_paths('/Transcripts/')


def test_validate_exclude_paths_non_string_entry_is_fatal():
    with pytest.raises(SystemExit):
        h.validate_exclude_paths(['/a/', 123])


def test_validate_exclude_paths_empty_string_is_fatal():
    # '' is a substring of every path: it would exclude everything, silently
    # disabling britfix. Reject it outright.
    with pytest.raises(SystemExit):
        h.validate_exclude_paths([''])


# --- path_is_excluded (matching) -------------------------------------------

def test_path_is_excluded_match():
    assert h.path_is_excluded('/home/u/Transcripts/ep.md', ['/Transcripts/'])


def test_path_is_excluded_no_match():
    assert not h.path_is_excluded('/home/u/notes/ep.md', ['/Transcripts/'])


def test_path_is_excluded_empty_list():
    assert not h.path_is_excluded('/home/u/anything.md', [])


def test_path_is_excluded_substring_footgun():
    # Documents the naive-substring sharp edge: 'notes' also matches 'footnotes'.
    assert h.path_is_excluded('/home/u/footnotes/ep.md', ['notes'])


def test_path_is_excluded_posix_form():
    # Entries use forward slashes; matching is on the resolved posix form.
    assert h.path_is_excluded('/home/u/a/b/ep.md', ['a/b'])


# --- process_posttooluse integration ---------------------------------------

def _payload(fp):
    return {"hook_event_name": "PostToolUse", "tool_name": "Write",
            "tool_input": {"file_path": fp}}


@pytest.fixture
def md_file(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("the color is nice")
    return str(f)


def test_process_skips_excluded(monkeypatch, md_file):
    """An excluded file must short-circuit before britfix runs."""
    calls = []
    monkeypatch.setattr(h, "run_britfix", lambda fp: (calls.append(fp), (True, ""))[1])
    monkeypatch.setattr(h, "EXCLUDE_PATHS", ["note.md"])
    monkeypatch.setattr(h, "SUPPORTED_EXTENSIONS", {".md"})
    h.process_posttooluse(_payload(md_file))
    assert calls == []  # excluded -> britfix never invoked


def test_process_runs_when_not_excluded(monkeypatch, md_file):
    """A supported, non-excluded file must be processed normally."""
    calls = []
    monkeypatch.setattr(h, "run_britfix", lambda fp: (calls.append(fp), (True, ""))[1])
    monkeypatch.setattr(h, "EXCLUDE_PATHS", ["/nonexistent-fragment-xyz/"])
    monkeypatch.setattr(h, "SUPPORTED_EXTENSIONS", {".md"})
    h.process_posttooluse(_payload(md_file))
    assert calls == [md_file]  # not excluded -> britfix invoked


# --- merge_local_config (config.local.json) --------------------------------

def _base_config():
    return {"strategies": {}, "exclude_paths": ["/shared/"]}


def _local(tmp_path, content):
    p = tmp_path / "config.local.json"
    p.write_text(content if isinstance(content, str) else json.dumps(content))
    return p


def test_merge_local_missing_file_is_noop(tmp_path):
    cfg = _base_config()
    assert h.merge_local_config(cfg, tmp_path / "config.local.json") == _base_config()


def test_merge_local_extends_exclude_paths(tmp_path):
    cfg = h.merge_local_config(_base_config(), _local(tmp_path, {"exclude_paths": ["/private/"]}))
    assert cfg["exclude_paths"] == ["/shared/", "/private/"]


def test_merge_local_comment_keys_allowed(tmp_path):
    cfg = h.merge_local_config(_base_config(), _local(tmp_path, {"comment": "mine", "exclude_paths": []}))
    assert cfg["exclude_paths"] == ["/shared/"]


def test_merge_local_invalid_json_is_fatal(tmp_path):
    with pytest.raises(SystemExit):
        h.merge_local_config(_base_config(), _local(tmp_path, "{not json"))


def test_merge_local_unreadable_file_is_fatal(tmp_path):
    # An existing-but-unreadable local file (here: a directory) must fail
    # closed with a clear error, not crash with an uncaught OSError.
    p = tmp_path / "config.local.json"
    p.mkdir()
    with pytest.raises(SystemExit):
        h.merge_local_config(_base_config(), p)


def test_merge_local_comment_substring_key_is_fatal(tmp_path):
    # Only 'comment' and '*_comment' are comment keys; a key merely containing
    # the substring must still be rejected.
    with pytest.raises(SystemExit):
        h.merge_local_config(_base_config(), _local(tmp_path, {"uncommented": True}))


def test_merge_local_non_object_is_fatal(tmp_path):
    with pytest.raises(SystemExit):
        h.merge_local_config(_base_config(), _local(tmp_path, ["/private/"]))


def test_merge_local_strategies_override_is_fatal(tmp_path):
    # strategies must stay in the shared config: the CLI loads config.json
    # independently, so a hook-only override would desync the two.
    with pytest.raises(SystemExit):
        h.merge_local_config(_base_config(), _local(tmp_path, {"strategies": {}}))


def test_merge_local_entries_are_validated(tmp_path):
    with pytest.raises(SystemExit):
        h.merge_local_config(_base_config(), _local(tmp_path, {"exclude_paths": [""]}))
