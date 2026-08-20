#!/usr/bin/env python3
"""Tests for britfix_hook — exclude_paths validation and path-based skipping."""
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
