#!/usr/bin/env python3
"""Tests for britfix_hook — exclude_paths validation, path-based skipping and
the change report the hook surfaces after a rewrite."""
import json
import os
import subprocess
import time
import unittest.mock as mock
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
    monkeypatch.setattr(h, "run_britfix", lambda fp: (calls.append(fp), (True, "", []))[1])
    monkeypatch.setattr(h, "EXCLUDE_PATHS", ["note.md"])
    monkeypatch.setattr(h, "SUPPORTED_EXTENSIONS", {".md"})
    h.process_posttooluse(_payload(md_file))
    assert calls == []  # excluded -> britfix never invoked


def test_process_runs_when_not_excluded(monkeypatch, md_file):
    """A supported, non-excluded file must be processed normally."""
    calls = []
    monkeypatch.setattr(h, "run_britfix", lambda fp: (calls.append(fp), (True, "", []))[1])
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


# --- summarise_changes (the report is derived from the file, not the CLI) ---

def _b(text):
    return text.encode('utf-8')


def test_summarise_counts_one_occurrence_once():
    # Regression for the doubled count. The CLI prints every word twice, once in
    # the per-file block and once in the totals block, so the old regex over its
    # whole stdout reported 'Fixed 2' for a single correction. Counting the file
    # itself cannot double.
    s = h.summarise_changes(_b("the color is nice"), _b("the colour is nice"))
    assert s['total'] == 1
    assert s['items'] == [(1, 'color', 'colour')]


def test_summarise_pairs_several_words_on_one_line():
    s = h.summarise_changes(_b("color and center and analyze"),
                            _b("colour and centre and analyse"))
    assert [(old, new) for _, old, new in s['items']] == [
        ('color', 'colour'), ('center', 'centre'), ('analyze', 'analyse')]


def test_summarise_reports_line_numbers():
    # Line numbers are what let a reader tell a prose correction from a
    # corrupted machine token, and they cost nothing: the same diff yields them.
    before = _b("clean\nthe color\nclean\nthe center\n")
    after = _b("clean\nthe colour\nclean\nthe centre\n")
    s = h.summarise_changes(before, after)
    assert [(line, old) for line, old, _ in s['items']] == [(2, 'color'), (4, 'center')]


def test_summarise_leaves_untouched_tokens_out_of_the_report():
    # Only the comment changed here; the OOXML attribute did not. The report
    # must say so rather than naming every candidate word on the line.
    before = _b('w:color="auto"  # the color here')
    after = _b('w:color="auto"  # the colour here')
    s = h.summarise_changes(before, after)
    assert s['total'] == 1


def test_summarise_identical_is_no_change():
    s = h.summarise_changes(_b("same"), _b("same"))
    assert s['changed'] is False
    assert s['items'] == []


def test_summarise_unreadable_side_is_no_change():
    # read_file_bytes returns None when the file vanished or became unreadable
    # between the edit and the hook; that must report nothing, not raise.
    assert h.summarise_changes(None, _b("x"))['changed'] is False
    assert h.summarise_changes(_b("x"), None)['changed'] is False


def test_summarise_line_count_change_falls_back_to_no_detail():
    # An in-place word substitution never changes the line count; a truncated
    # write does. Say a change happened without inventing a count.
    s = h.summarise_changes(_b("a\nb\n"), _b("a\n"))
    assert s['changed'] is True
    assert s['detailed'] is False
    assert s['total'] == 0


def test_summarise_undecodable_bytes_do_not_raise():
    s = h.summarise_changes(b"\xff\xfe color", b"\xff\xfe colour")
    assert s['changed'] is True


def test_summarise_line_ending_only_change_is_not_a_spelling_report():
    # A BOM or line-ending difference changes the bytes but corrects nothing.
    s = h.summarise_changes(_b("a\nb"), _b("a\r\nb"))
    assert s['changed'] is True
    assert s['detailed'] is False


def test_format_change_list_caps_and_summarises_the_remainder():
    items = [(i, 'color', 'colour') for i in range(1, 9)]
    rendered = h.format_change_list(items)
    assert rendered.count('->') == h.MAX_REPORTED_CHANGES
    assert rendered.endswith('+3 more')


# --- build_hook_output (what the user and the model actually receive) -------

def _changed(before="the color", after="the colour"):
    return h.summarise_changes(_b(before), _b(after))


def test_output_reports_a_change_to_both_user_and_model():
    out = h.build_hook_output('/repo/notes.md', _changed(), '', [])
    assert out['systemMessage'].startswith('britfix rewrote 1 spelling in /repo/notes.md')
    assert out['hookSpecificOutput']['hookEventName'] == 'PostToolUse'
    assert 'additionalContext' in out['hookSpecificOutput']


def test_output_names_the_full_path_not_the_basename():
    # A basename cannot distinguish a prose correction from a corrupted
    # attribute among several like-named files (issue #63).
    out = h.build_hook_output('/repo/deep/notes.md', _changed(), '', [])
    assert '/repo/deep/notes.md' in out['systemMessage']


def test_output_tells_the_model_not_to_revert_the_change():
    # additionalContext reaches the model that just made the edit. If it reads
    # as a complaint, the model's next move is to put the US spelling back, the
    # hook corrects it again, and the two loop; issue #53 records that happening.
    out = h.build_hook_output('/repo/notes.md', _changed(), '', [])
    ctx = out['hookSpecificOutput']['additionalContext']
    assert 'must not be reverted' in ctx
    assert '.britfixignore' in ctx


def test_output_is_empty_when_nothing_changed():
    # The hook fires after every Write and Edit on 35 extensions. Silence on a
    # file it did not touch is what keeps that bearable.
    assert h.build_hook_output('/repo/notes.md', _changed("same", "same"), '', []) == {}


def test_output_reports_a_cli_failure_to_the_user():
    out = h.build_hook_output('/repo/notes.md', _changed("same", "same"), 'uv not found', [])
    assert 'uv not found' in out['systemMessage']


def test_output_reports_a_skip_to_the_model_only():
    # 'britfix skipped this file' explains to the model why the US spellings it
    # wrote are still present. It is not a warning the user needs.
    note = 'britfix: skipped {"path": "/repo/a.tex", "reason": "unterminated math"}'
    out = h.build_hook_output('/repo/a.tex', _changed("same", "same"), '', [note])
    assert 'unterminated math' in out['hookSpecificOutput']['additionalContext']
    assert 'systemMessage' not in out


def test_output_strings_stay_well_under_the_ten_thousand_character_cap():
    # Claude Code replaces an over-long hook string with a preview and a file
    # path, which would stop the JSON parsing.
    items = [(i, 'color', 'colour') for i in range(1, 500)]
    summary = {'changed': True, 'detailed': True, 'total': len(items), 'items': items}
    out = h.build_hook_output('/repo/notes.md', summary, '', [])
    assert len(out['systemMessage']) <= h.MAX_MESSAGE_CHARS
    assert len(out['hookSpecificOutput']['additionalContext']) <= h.MAX_MESSAGE_CHARS


# --- run_britfix (no longer reads the CLI's prose) --------------------------

def test_run_britfix_ignores_cli_stdout_wording():
    # The hook no longer parses the CLI summary at all, so rewording it cannot
    # change the report. This stdout is the exact shape that used to double.
    class Result:
        returncode = 0
        stdout = "  color -> colour: 1 occurrence(s)\n  color -> colour: 1 occurrence(s)\n"
        stderr = ""

    with mock.patch.object(h.subprocess, 'run', return_value=Result()):
        assert h.run_britfix('/tmp/x.md') == (True, "", [])


def test_run_britfix_collects_skip_diagnostics():
    note = 'britfix: skipped {"path": "/a.tex", "reason": "unterminated math"}'

    class Result:
        returncode = 0
        stdout = ""
        stderr = note + "\n"

    with mock.patch.object(h.subprocess, 'run', return_value=Result()):
        ok, error, skipped = h.run_britfix('/tmp/x.tex')
    assert (ok, error, skipped) == (True, "", [note])


def test_run_britfix_timeout_is_not_fatal():
    with mock.patch.object(h.subprocess, 'run',
                           side_effect=subprocess.TimeoutExpired(cmd='britfix', timeout=10)):
        assert h.run_britfix('/tmp/x.md') == (False, "Timeout", [])


# --- main(): a valid JSON object and exit 0 on every path -------------------
#
# A malformed payload or a non-zero exit would break every Write and Edit in the
# session, so each of these asserts both, not just the behaviour under test.

def _drive_main(monkeypatch, capsys, payload, result=(True, "", []), during_run=None):
    """Run main() with britfix stubbed. Returns (exit_code, parsed_stdout)."""
    def fake_run_britfix(file_path):
        if during_run:
            during_run(file_path)
        return result

    monkeypatch.setattr(h, "read_hook_input", lambda *a, **k: payload)
    monkeypatch.setattr(h, "run_britfix", fake_run_britfix)
    monkeypatch.setattr(h, "EXCLUDE_PATHS", [])
    monkeypatch.setattr(h, "SUPPORTED_EXTENSIONS", {".md"})
    code = h.main()
    return code, json.loads(capsys.readouterr().out)


def test_main_normal_change(monkeypatch, capsys, md_file):
    def correct(file_path):
        with open(file_path, 'w') as f:
            f.write("the colour is nice")

    code, out = _drive_main(monkeypatch, capsys, _payload(md_file), during_run=correct)
    assert code == 0
    assert out['systemMessage'].endswith("L1 color->colour")
    assert out['hookSpecificOutput']['hookEventName'] == 'PostToolUse'


def test_main_no_change_says_nothing(monkeypatch, capsys, md_file):
    code, out = _drive_main(monkeypatch, capsys, _payload(md_file))
    assert code == 0
    assert out == {}


def test_main_unsupported_extension(monkeypatch, capsys, tmp_path):
    other = tmp_path / "image.bin"
    other.write_text("the color is nice")
    code, out = _drive_main(monkeypatch, capsys, _payload(str(other)))
    assert code == 0
    assert out == {}


def test_main_excluded_path(monkeypatch, capsys, md_file):
    monkeypatch.setattr(h, "read_hook_input", lambda *a, **k: _payload(md_file))
    monkeypatch.setattr(h, "run_britfix", lambda fp: (True, "", []))
    monkeypatch.setattr(h, "EXCLUDE_PATHS", ["note.md"])
    monkeypatch.setattr(h, "SUPPORTED_EXTENSIONS", {".md"})
    code = h.main()
    assert code == 0
    assert json.loads(capsys.readouterr().out) == {}


def test_main_timeout(monkeypatch, capsys, md_file):
    code, out = _drive_main(monkeypatch, capsys, _payload(md_file), result=(False, "Timeout", []))
    assert code == 0
    assert "Timeout" in out['systemMessage']


def test_main_cli_failure(monkeypatch, capsys, md_file):
    code, out = _drive_main(monkeypatch, capsys, _payload(md_file),
                            result=(False, "britfix.py: boom", []))
    assert code == 0
    assert "boom" in out['systemMessage']


def test_main_file_deleted_between_the_edit_and_the_hook(monkeypatch, capsys, tmp_path):
    missing = tmp_path / "gone.md"
    code, out = _drive_main(monkeypatch, capsys, _payload(str(missing)))
    assert code == 0
    assert out == {}


def test_main_file_deleted_mid_run(monkeypatch, capsys, md_file):
    # The file existed when the hook started and vanished while britfix ran, so
    # the after-read fails. That must not raise and must not invent a report.
    code, out = _drive_main(monkeypatch, capsys, _payload(md_file),
                            during_run=lambda fp: os.remove(fp))
    assert code == 0
    assert out == {}


def test_main_survives_a_broken_summariser(monkeypatch, capsys, md_file):
    # A bug in the reporting code must cost the report, never the edit.
    def explode(*args, **kwargs):
        raise RuntimeError("summariser bug")

    monkeypatch.setattr(h, "summarise_changes", explode)
    code, out = _drive_main(monkeypatch, capsys, _payload(md_file))
    assert code == 0
    assert out == {}


def test_main_ignores_other_hook_events(monkeypatch, capsys):
    monkeypatch.setattr(h, "read_hook_input", lambda *a, **k: {"hook_event_name": "PreToolUse"})
    code = h.main()
    assert code == 0
    assert json.loads(capsys.readouterr().out) == {}


def test_main_does_not_echo_the_input_payload(monkeypatch, capsys, md_file):
    # The echo was not required by the hook contract and actively broke it: for
    # a large Write, tool_input.content pushed stdout past the 10,000 character
    # output cap, at which point the payload is replaced by a preview and stops
    # being parseable JSON, taking the report with it.
    payload = _payload(md_file)
    payload['tool_input']['content'] = 'x' * 20000
    code, out = _drive_main(monkeypatch, capsys, payload)
    assert code == 0
    assert out == {}


def test_output_keeps_the_revert_instruction_whatever_the_path_length():
    # The instruction not to revert is the part that stops a hook/model loop,
    # so it must survive a pathological path rather than being truncated away.
    long_path = '/repo/' + ('deep/' * 400) + 'notes.md'
    out = h.build_hook_output(long_path, _changed(), '', [])
    ctx = out['hookSpecificOutput']['additionalContext']
    assert len(ctx) <= h.MAX_MESSAGE_CHARS
    assert 'must not be reverted' in ctx
    assert '.britfixignore' in ctx


def test_summarise_refuses_to_explain_a_diff_that_is_not_a_spelling_change():
    # The before-read and the after-read straddle the corrector, so another
    # writer can land inside that window. A structural edit is not a spelling
    # correction, and attributing it to britfix would be a confident lie.
    s = h.summarise_changes(_b("the color is nice"), _b("the color is nice  # added by someone"))
    assert s['changed'] is True
    assert s['detailed'] is False
    assert s['items'] == []


def test_summarise_still_explains_a_correction_inside_a_machine_token():
    # The guard above must not suppress the case issue #63 is about: a
    # correction landing inside an OOXML attribute is still word-for-word.
    s = h.summarise_changes(_b('w:color="auto"'), _b('w:colour="auto"'))
    assert s['detailed'] is True
    assert s['items'] == [(1, 'color', 'colour')]


def test_output_does_not_claim_britfix_made_an_unexplained_change():
    # Saying less beats saying something false: with no word-level explanation,
    # the message asserts that the file differs, not who changed it, and gives
    # no revert instruction it cannot justify.
    summary = {'changed': True, 'detailed': False, 'total': 0, 'items': []}
    out = h.build_hook_output('/repo/notes.md', summary, '', [])
    assert 'britfix rewrote' not in out['systemMessage']
    ctx = out['hookSpecificOutput']['additionalContext']
    assert 'must not be reverted' not in ctx
    assert 'Re-read the file' in ctx


def test_summarise_explains_a_prefix_correction_that_keeps_its_hyphen():
    # estr- to oestr- and paleo- to palaeo- keep the trailing hyphen.
    s = h.summarise_changes(_b("an estr-levels study"), _b("an oestr-levels study"))
    assert s['detailed'] is True
    assert s['items'] == [(1, 'estr', 'oestr')]


def test_summarise_explains_a_prefix_correction_that_drops_its_hyphen():
    # feto- to foeto and leuk- to leuc drop it, so the replacement changes the
    # shape of the line. A narrower signature rejected these, and because the
    # check collapses the whole file's report, one such pair would have taken
    # every other explained correction in the file down with it.
    s = h.summarise_changes(_b("a feto-scan today"), _b("a foetoscan today"))
    assert s['detailed'] is True
    assert s['items'] == [(1, 'feto-scan', 'foetoscan')]


def test_is_correction_shaped_rejects_anything_that_is_not_a_word():
    # The guard's whole value is what it refuses. A machine token, a span with
    # punctuation or spaces in it, a number, or a bare hyphen are not spelling
    # corrections and must not be reported as though britfix made them.
    assert h.is_correction_shaped('color')
    assert h.is_correction_shaped('feto-scan')
    assert not h.is_correction_shaped('w:color')
    assert not h.is_correction_shaped('color is nice  # added')
    assert not h.is_correction_shaped('1')
    assert not h.is_correction_shaped('-')
    assert not h.is_correction_shaped('')


# --- bounded work and non-regular files ------------------------------------

def test_a_very_long_line_is_not_summarised_and_returns_promptly():
    # The matcher is quadratic in line length and runs after the CLI subprocess
    # timeout has already been spent, so nothing else can stop it. A single
    # unwrapped line (a minified asset, a one-line JSON or CSS blob) took about
    # 50 seconds at 138 KB before this bound, with the session stalled and no
    # output to explain it. Over budget, the file falls through to the existing
    # no-detail report, which is safe and immediate.
    line = ("The color of the organization was analyzed at the center here. " * 3000)
    before = line.encode()
    after = line.replace("color", "colour", 5).encode()
    started = time.perf_counter()
    s = h.summarise_changes(before, after)
    elapsed = time.perf_counter() - started
    assert s['changed'] is True
    assert s['detailed'] is False
    assert elapsed < 5.0, f"took {elapsed:.1f}s: the work bound is not holding"


def test_an_ordinary_unwrapped_paragraph_is_still_summarised():
    # The bound must not cost the normal case. A long hand-written paragraph
    # without hard wrapping is well inside it.
    line = "The color scheme " + ("of assorted things and various other matters " * 100)
    before = line.encode()
    after = line.replace("color", "colour").encode()
    s = h.summarise_changes(before, after)
    assert s['detailed'] is True
    assert s['items'] == [(1, 'color', 'colour')]


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason="no FIFOs on this platform")
def test_read_file_bytes_does_not_block_on_a_fifo(tmp_path):
    # A plain open() on a FIFO with no writer blocks for ever, and this runs
    # after every edit, so it would wedge the session with no timeout to rescue
    # it. OSError never fires for that case: the call simply never returns.
    fifo = tmp_path / "pipe.md"
    os.mkfifo(str(fifo))
    started = time.perf_counter()
    assert h.read_file_bytes(str(fifo)) is None
    assert time.perf_counter() - started < 5.0


def test_read_file_bytes_returns_none_for_a_directory(tmp_path):
    assert h.read_file_bytes(str(tmp_path)) is None


def test_read_file_bytes_reads_a_regular_file(tmp_path):
    f = tmp_path / "note.md"
    f.write_bytes(b"the color")
    assert h.read_file_bytes(str(f)) == b"the color"


# --- insertions and deletions are not corrections ---------------------------

def test_an_inserted_word_is_not_reported_as_a_correction():
    # britfix substitutes words in place; it never inserts one. An insertion
    # means another writer reached the file inside the window between the
    # before-read and the after-read, and calling that a correction would
    # attach the do-not-revert instruction to someone else's edit.
    s = h.summarise_changes(_b("the color is nice"), _b("the color is really nice"))
    assert s['changed'] is True
    assert s['detailed'] is False
    assert s['items'] == []


def test_a_deleted_word_is_not_reported_as_a_correction():
    s = h.summarise_changes(_b("the color is really nice"), _b("the color is nice"))
    assert s['changed'] is True
    assert s['detailed'] is False


def test_a_correction_beside_a_foreign_insertion_is_not_reported():
    # The corrections are real, but the line also gained a word, so the line as
    # a whole is not explained and nothing from it is claimed.
    s = h.summarise_changes(_b("the color is nice"), _b("the colour is really nice"))
    assert s['detailed'] is False


# --- line numbers count lines, not control characters -----------------------

def test_line_numbers_ignore_form_feeds_and_unicode_separators():
    # str.splitlines() splits on form feed, vertical tab, NEL and U+2028 among
    # others, none of which an editor counts as a line, so every later line
    # number would be reported one too high. This module's family has a history
    # here: a form-feed offset once produced 'colourr'.
    before = _b("alpha\x0cbeta\nthe color\n")
    after = _b("alpha\x0cbeta\nthe colour\n")
    s = h.summarise_changes(before, after)
    assert s['items'] == [(2, 'color', 'colour')]


def test_line_numbers_are_right_after_a_unicode_line_separator():
    before = "alpha beta\nthe color\n".encode('utf-8')
    after = "alpha beta\nthe colour\n".encode('utf-8')
    s = h.summarise_changes(before, after)
    assert s['items'] == [(2, 'color', 'colour')]


def test_crlf_line_endings_still_count_correctly():
    before = _b("alpha\r\nthe color\r\n")
    after = _b("alpha\r\nthe colour\r\n")
    s = h.summarise_changes(before, after)
    assert s['items'] == [(2, 'color', 'colour')]


# --- a broken .britfixignore entry must not be swallowed --------------------

def test_unknown_strategy_diagnostic_is_forwarded():
    # The hook's own message tells the model to edit .britfixignore, so when the
    # model gets the syntax wrong the CLI's complaint has to reach someone.
    note = "britfix: unknown strategy 'w' in .britfixignore, skipping"

    class Result:
        returncode = 0
        stdout = ""
        stderr = note + "\n"

    with mock.patch.object(h.subprocess, 'run', return_value=Result()):
        ok, error, diagnostics = h.run_britfix('/tmp/x.md')
    assert diagnostics == [note]


def test_unknown_strategy_is_reported_to_both_user_and_model():
    note = "britfix: unknown strategy 'w' in .britfixignore, skipping"
    out = h.build_hook_output('/repo/notes.md', _changed("same", "same"), '', [note])
    assert 'unknown strategy' in out['systemMessage']
    ctx = out['hookSpecificOutput']['additionalContext']
    assert 'exempts nothing' in ctx
    assert 'quoted' in ctx


def test_malformed_json_diagnostic_is_treated_as_a_skip():
    # A file-level skip explains why nothing changed; it is not a config fault,
    # so it goes to the model and not to the user as a warning.
    note = "britfix: skipping malformed JSON (Expecting value at line 1, column 1)"
    out = h.build_hook_output('/repo/a.json', _changed("same", "same"), '', [note])
    assert 'systemMessage' not in out
    assert 'malformed JSON' in out['hookSpecificOutput']['additionalContext']
