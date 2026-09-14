import ast
from pathlib import Path
import subprocess
import sys

import pytest

import britfix
import britfix_core as core
from britfix_python import ProcessingSkipped


@pytest.fixture
def corrector():
    return core.SpellingCorrector({'color': 'colour', 'behavior': 'behaviour', 'finalize': 'finalise'})


def test_dispatch_and_identifier_documentation(corrector):
    source = '''def f(color=True):
    """Args:
        color: Enable behavior.
        colour: Alias for color.
    """
    return color
'''
    strategy = core.get_file_strategy('.py')
    result, changes = strategy.process(source, corrector)
    assert result == source.replace('behavior', 'behaviour')
    assert changes == {'behavior': 1}
    assert core.get_file_strategy_name('.py') == 'code'
    assert isinstance(core.get_file_strategy('.js'), core.CodeStrategy)


@pytest.mark.parametrize('literal', [
    '["""<w:color w:val="color"/>"""]',
    'str("""<w:color/>""")',
    'f"color {1 + 2}"',
    '"color" "behavior"',
    'r"color\\behavior"',
])
def test_non_docstring_literals_unchanged(corrector, literal):
    source = f'value = {literal}\n# The behavior is intentional.\n'
    result, _ = core.get_file_strategy('.py').process(source, corrector)
    # Concatenated value is 'colorbehavior', so neither separate word is a key.
    expected = source.replace('# The behavior', '# The behaviour')
    assert result == expected


def test_shebang_and_string_key_references(corrector):
    source = '#!/opt/color/bin/python\nkey = "color"\n# unknown key (colour, not color); behavior\n'
    result, _ = core.get_file_strategy('.py').process(source, corrector)
    assert result == source.replace('; behavior', '; behaviour')


@pytest.mark.parametrize('label', ['color:', 'color : bool', ':param color:'])
def test_parameter_styles_and_unrelated_prose(corrector, label):
    source = f'def f():\n    """\n    {label} behavior\n    """\n'
    assert core.get_file_strategy('.py').process(source, corrector)[0] == source.replace('behavior', 'behaviour')


def test_unicode_positions_and_quoted_references(corrector):
    source = 'def f():\n    """é behavior `color` xref.finalize https://example.org/color"""\n'
    result, _ = core.get_file_strategy('.py').process(source, corrector)
    assert result == source.replace('behavior', 'behaviour')
    assert ast.parse(result)


def test_unsupported_compound_docstring_preserved(corrector):
    source = 'def f():\n    "color" "behavior"\n# behavior\n'
    assert core.get_file_strategy('.py').process(source, corrector)[0] == source.replace('# behavior', '# behaviour')


@pytest.mark.parametrize('source', ['def f(color:', '"""color', 'def f():\n  pass\n pass\n'])
def test_invalid_source_is_a_skip_even_without_candidates(corrector, source):
    with pytest.raises(ProcessingSkipped):
        core.get_file_strategy('.py').process(source, corrector)


def test_protected_names_do_not_leak_between_files(corrector):
    strategy = core.get_file_strategy('.py')
    assert strategy.process('color = 1\n# color\n', corrector)[0].endswith('# color\n')
    assert strategy.process('# color\n', corrector)[0] == '# colour\n'


@pytest.mark.parametrize('extension,body', [
    ('.md', b'color\r\n```\r\ncolor\r\n```\n'),
    ('.py', b'#!/opt/color/python\r\n# behavior\npass\r\n'),
    ('.tex', b'color\r\n'), ('.txt', b'color\r\n'),
    ('.html', b'<b>color</b>\r\n'), ('.css', b'/* color */\r\n'),
    ('.js', b'// color\r\nconst value = "color";\n'),
])
def test_cli_preserves_bom_and_line_endings(tmp_path, extension, body):
    path = tmp_path / ('input' + extension)
    original = b'\xef\xbb\xbf' + body
    path.write_bytes(original)
    command = [sys.executable, str(Path(britfix.__file__)), '--input', str(path), '--no-backup']
    dry = subprocess.run(command + ['--dry-run'], capture_output=True)
    assert dry.returncode == 0
    assert path.read_bytes() == original
    run = subprocess.run(command, capture_output=True)
    assert run.returncode == 0, run.stderr
    expected_body = body.replace(b'# behavior', b'# behaviour') if extension == '.py' else body.replace(b'color', b'colour', 1)
    assert path.read_bytes() == b'\xef\xbb\xbf' + expected_body


def test_cli_skip_summary_and_hook_relay(tmp_path, monkeypatch, capsys):
    import britfix_hook

    path = tmp_path / 'broken.py'
    path.write_text('def f(color:')
    command = [sys.executable, str(Path(britfix.__file__)), '--input', str(path)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stderr.startswith('britfix: skipped ')
    assert 'skipped: 1' in result.stdout
    assert 'No changes were needed' not in result.stdout
    assert path.read_text() == 'def f(color:'
    monkeypatch.setattr(britfix_hook.subprocess, 'run', lambda *a, **k: result)
    assert britfix_hook.run_britfix(str(path))[0]
    assert 'britfix: skipped ' in capsys.readouterr().err


def test_invalid_utf8_skip(tmp_path):
    path = tmp_path / 'input.md'
    path.write_bytes(b'color\xff')
    result = subprocess.run([sys.executable, str(Path(britfix.__file__)), '--input', str(path)], capture_output=True)
    assert b'britfix: skipped ' in result.stderr
    assert path.read_bytes() == b'color\xff'


@pytest.mark.parametrize('extension,source', [
    ('.md', 'color https://example.org/color'),
    ('.py', '#!/opt/color/python\n# behavior\n'),
    ('.tex', 'color'),
])
@pytest.mark.parametrize('choice', ['a', 'q'])
def test_interactive_real_write_matches_selection(tmp_path, monkeypatch, extension, source, choice):
    path = tmp_path / ('interactive' + extension)
    original = b'\xef\xbb\xbf' + source.replace('\n', '\r\n').encode()
    path.write_bytes(original)
    monkeypatch.setattr(britfix, 'get_input', lambda: choice)
    monkeypatch.setattr(britfix, 'clear_screen', lambda: None)
    monkeypatch.setattr(sys, 'argv', ['britfix', '--input', str(path), '--interactive', '--no-backup'])
    britfix.main()
    if choice == 'q':
        assert path.read_bytes() == original
    else:
        strategy = core.get_file_strategy(extension)
        before = source.replace('\n', '\r\n')
        expected, _ = strategy.process(before, core.SpellingCorrector(core.load_spelling_mappings()))
        assert path.read_bytes() == b'\xef\xbb\xbf' + expected.encode()


def test_ast_unchanged_except_docstring_text(corrector):
    source = 'class É: """behavior"""\n'
    result, _ = core.get_file_strategy('.py').process(source, corrector)
    assert result == source.replace('behavior', 'behaviour')
    trees = [ast.parse(text) for text in [source, result]]
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                    node.body[0].value.value = ''
    assert ast.dump(trees[0]) == ast.dump(trees[1])
