import ast
import copy
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

import britfix
import britfix_core as core
from britfix_python import ProcessingSkipped, PythonStrategy


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
    log_path = tmp_path / 'hook.log'
    monkeypatch.setattr(britfix_hook, 'LOG_FILE', str(log_path))
    monkeypatch.setattr(britfix_hook.subprocess, 'run', lambda *a, **k: result)
    assert britfix_hook.run_britfix(str(path))[0]
    assert 'britfix: skipped ' in capsys.readouterr().err
    assert 'britfix: skipped ' in log_path.read_text()


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


WORDS = {
    'color': 'colour', 'behavior': 'behaviour', 'analyzed': 'analysed',
    'organized': 'organised', 'finalize': 'finalise', 'center': 'centre',
}
MODES = ['defined', 'all']
SEPARATORS = ['\x0b', '\x0c', '\x1c', '\x1d', '\x1e', '\x85', '\u2028', '\u2029']


@pytest.fixture
def words():
    return core.SpellingCorrector(WORDS)


def to_us(text):
    for us, uk in WORDS.items():
        text = text.replace(uk, us)
    return text


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('sep', SEPARATORS)
@pytest.mark.parametrize('template', [
    '# a{sep}b\n# The color was analyzed.\n# The behavior was organized.\nx = 1\n',
    'def f():\n    """a{sep}b\n    The color was analyzed.\n    """\n    # The behavior was organized.\n    return 1\n',
    'x = "a{sep}b"\n# The color was analyzed.\ndef f():\n    """The behavior was organized."""\n',
])
def test_unicode_line_separators_do_not_shift_offsets(words, mode, sep, template):
    source = template.format(sep=sep)
    expected = (source.replace('color was analyzed', 'colour was analysed')
                .replace('behavior was organized', 'behaviour was organised'))
    assert PythonStrategy(mode).process(source, words)[0] == expected


@pytest.mark.parametrize('mode', MODES)
def test_lone_cr_before_docstring_uses_parser_rows(words, mode):
    source = 'x = 1  # a\rb\ndef f():\n    """The color was analyzed."""\n# The behavior\n'
    expected = source.replace('color was analyzed', 'colour was analysed').replace('The behavior', 'The behaviour')
    assert PythonStrategy(mode).process(source, words)[0] == expected


def shifted_rows(real, which, delta=1):
    def fake(content, pattern):
        starts = real(content, pattern)
        if which is None or pattern is which:
            return [0] + [s + delta for s in starts[1:-1]] + starts[-1:]
        return starts
    return fake


def test_offset_guard_skips_file_without_writing(tmp_path, monkeypatch, capsys):
    import britfix_python

    path = tmp_path / 'guarded.py'
    original = b'x = 1\n# The color was analyzed.\n# The behavior was organized.\n'
    path.write_bytes(original)
    monkeypatch.setattr(britfix_python, '_row_starts', shifted_rows(britfix_python._row_starts, None))
    monkeypatch.setattr(sys, 'argv', ['britfix', '--input', str(path), '--no-backup'])
    britfix.main()
    assert path.read_bytes() == original
    err = capsys.readouterr().err
    assert 'britfix: skipped ' in err
    assert 'offsets inconsistent' in err


def test_docstring_guard_skips(words, monkeypatch):
    import britfix_python

    monkeypatch.setattr(britfix_python, '_row_starts',
                        shifted_rows(britfix_python._row_starts, britfix_python.AST_ROWS, -1))
    source = 'x = 1\ndef f():\n    """The color was analyzed."""\n'
    with pytest.raises(ProcessingSkipped, match='offsets inconsistent'):
        PythonStrategy('defined').process(source, words)


def test_replacement_guard_skips():
    class Misaligned:
        def find_replacements(self, text):
            return [(0, 5, 'color', 'colour')]

    with pytest.raises(ProcessingSkipped, match='offsets inconsistent'):
        PythonStrategy('defined').process('# The color\n', Misaligned())


MATPLOTLIB = (
    'import matplotlib.pyplot as plt\n\n'
    'def draw(ax):\n'
    '    # Pick a color that suits the behavior of the chart.\n'
    '    ax.plot([1], [2], color="red")\n'
)

ISSUE_53 = '''class PlainTextFormatter:
    def __init__(self, color: bool = True, colour: bool | None = None, quiet: bool = False):
        """
        Initialise formatter.

        Args:
            color: Enable ANSI colours. Auto-detected if stdout is TTY.
            colour: Alias for color (British spelling).
            quiet: Only show errors, suppress warnings and info.
        """
        self.quiet = quiet
'''

ISSUE_63 = '''import xref


def build():
    # Call xref.finalize before saving.
    xref.finalize()


def test_unknown_key():
    # unknown key (colour, not color)
    assert not validate({"color": "red"})
'''


def test_matplotlib_keyword_is_not_a_definition(words):
    assert PythonStrategy('defined').process(MATPLOTLIB, words)[0] == (
        MATPLOTLIB.replace('a color', 'a colour').replace('the behavior', 'the behaviour'))
    assert PythonStrategy('all').process(MATPLOTLIB, words)[0] == MATPLOTLIB.replace('the behavior', 'the behaviour')


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('source', [ISSUE_53, ISSUE_63])
def test_issue_examples_unchanged_in_both_modes(words, mode, source):
    assert PythonStrategy(mode).process(source, words)[0] == source


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('definition', [
    'def color(): pass',
    'async def color(): pass',
    'class color: pass',
    'def f(color, /): pass',
    'def f(*color): pass',
    'def f(*, color): pass',
    'def f(**color): pass',
    'f = lambda color: 0',
    'color = 1',
    'color: int = 1',
    'color += 1',
    'for color in []: pass',
    'with open("x") as color: pass',
    'try:\n    pass\nexcept OSError as color:\n    pass',
    '[0 for color in []]',
    '(color := 1)',
    'match x:\n    case [*color]: pass',
    'match x:\n    case {**color}: pass',
    'match x:\n    case P() as color: pass',
    'match x:\n    case color: pass',
    'def f():\n    global color',
    'def f():\n    def g():\n        nonlocal color',
    'import color',
    'import color.sub',
    'import other as color',
    'from pkg import color',
    'from pkg import other as color',
    'def f[color](): pass',
    'type color = int',
    'obj.color = 1',
    'self.color: int = 1',
])
def test_definitions_protect_prose_mentions(words, mode, definition):
    source = definition + '\n# The color\n'
    assert PythonStrategy(mode).process(source, words)[0] == source


@pytest.mark.parametrize('reference', [
    'ax.plot(color="red")',
    'value = obj.color',
    'obj.color()',
    'print(color)',
    'import pkg.color',
    'from pkg import color as tint',
])
def test_references_do_not_protect_under_defined(words, reference):
    source = reference + '\n# The color\n'
    assert PythonStrategy('defined').process(source, words)[0] == source.replace('# The color', '# The colour')
    # Every reference contains a color NAME token, so "all" still protects it.
    assert PythonStrategy('all').process(source, words)[0] == source


def test_load_only_attribute_call_does_not_protect(words):
    source = 'obj.center()\n# Keep the center aligned.\n'
    assert PythonStrategy('defined').process(source, words)[0] == source.replace('the center', 'the centre')
    assert PythonStrategy('all').process(source, words)[0] == source


def test_strategy_reads_config_at_process_time(words, monkeypatch):
    strategy = core.get_file_strategy('.py')
    monkeypatch.setitem(core._CONFIG['strategies']['code'], 'python_identifier_protection', 'all')
    assert strategy.process(MATPLOTLIB, words)[0] == MATPLOTLIB.replace('the behavior', 'the behaviour')
    monkeypatch.delitem(core._CONFIG['strategies']['code'], 'python_identifier_protection')
    assert 'a colour' in strategy.process(MATPLOTLIB, words)[0]


@pytest.mark.parametrize('value', ['Defined', 'ALL', 'none', '', True, None, ['all']])
def test_invalid_identifier_protection_rejected(monkeypatch, value):
    config = copy.deepcopy(core._CONFIG)
    config['strategies']['code']['python_identifier_protection'] = value
    monkeypatch.setattr('builtins.open', lambda *a, **k: io.StringIO(json.dumps(config)))
    with pytest.raises(core.ConfigError, match='code.python_identifier_protection must be "defined" or "all"'):
        core._load_config()


@pytest.mark.parametrize('value', ['defined', 'all', None])
def test_valid_identifier_protection_accepted(monkeypatch, value):
    config = copy.deepcopy(core._CONFIG)
    if value is None:
        config['strategies']['code'].pop('python_identifier_protection', None)
    else:
        config['strategies']['code']['python_identifier_protection'] = value
    monkeypatch.setattr('builtins.open', lambda *a, **k: io.StringIO(json.dumps(config)))
    assert core._load_config()['strategies']['code'].get('python_identifier_protection', 'defined') in MODES


def test_shipped_default_is_defined():
    assert core._CONFIG['strategies']['code']['python_identifier_protection'] == 'defined'
    with pytest.raises(ValueError):
        PythonStrategy('Defined')


@pytest.mark.parametrize('mode', MODES)
def test_cr_only_file_is_not_corrupted(words, mode):
    # Only a comment that opens the file tokenises as COMMENT; later comments stay unchanged.
    source = 'def f():\r    """The color was analyzed."""\r    return 1\r# The behavior\r# The color\r'
    result, _ = PythonStrategy(mode).process(source, words)
    assert result.endswith('    return 1\r# The behavior\r# The color\r')
    assert to_us(result) == source
    if mode == 'defined':
        # Under 'all' the tokenizer lexes CR-joined text as NAME tokens, protecting it.
        assert '"""The colour was analysed."""' in result

    source = '# The color opens\rdef f():\r    """The color was analyzed."""\r    return 1\r# The behavior\r'
    result, _ = PythonStrategy(mode).process(source, words)
    assert result.startswith('# The colour opens\r')
    assert result.endswith('    return 1\r# The behavior\r')
    assert to_us(result) == source
    ast.parse(result)
    if mode == 'defined':
        assert result == ('# The colour opens\rdef f():\r    """The colour was analysed."""\r'
                          '    return 1\r# The behavior\r')


NAMED_ESCAPE_WORDS = dict(WORDS, airplane='aeroplane')


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('source', [
    'def f():\n    """Icon is \\N{AIRPLANE} in color."""\n',
    'def f():\n    """Icon is \\N{airplane} in color."""\n',
    '"""Icon is \\N{AIRPLANE} in color."""\n',
    "class C:\n    '''Icon is \\N{airplane} in color.'''\n",
])
def test_named_unicode_escape_in_docstring_preserved(mode, source):
    result, _ = PythonStrategy(mode).process(source, core.SpellingCorrector(NAMED_ESCAPE_WORDS))
    assert result == source.replace('in color', 'in colour')
    ast.parse(result)


@pytest.mark.parametrize('mode', MODES)
def test_raw_docstring_named_escape_is_literal_text(mode):
    source = 'def f():\n    r"""Icon is \\N{airplane} in color."""\n'
    result, _ = PythonStrategy(mode).process(source, core.SpellingCorrector(NAMED_ESCAPE_WORDS))
    assert 'in colour' in result
    assert ast.parse(result)


def test_safety_net_skips_when_correction_breaks_parsing():
    class Breaking:
        def find_replacements(self, text):
            index = text.find('color')
            return [] if index < 0 else [(index, index + 5, 'color', 'col"""or')]

    source = 'def f():\n    """The color."""\n'
    with pytest.raises(ProcessingSkipped, match='would break parsing'):
        PythonStrategy('defined').process(source, Breaking())
    with pytest.raises(ProcessingSkipped, match='would break parsing'):
        PythonStrategy('defined').find_safe_replacements(source, Breaking())


def docstring(body, signature='def f(**kwargs):'):
    return signature + '\n    """Doc.\n\n' + body + '\n    """\n'


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('label', [
    'color:',
    'color : bool',
    'color (bool):',
    'color (bool, optional):',
    'color (int or None):',
    '*color (tuple):',
    '**color (dict):',
])
def test_google_labels_preserve_name_and_type(words, mode, label):
    source = docstring('    Args:\n        ' + label + ' The behavior.')
    assert PythonStrategy(mode).process(source, words)[0] == source.replace(
        'The behavior', 'The behaviour')


SPHINX_NAME_FIELDS = ['param', 'parameter', 'arg', 'argument', 'key', 'keyword',
                      'kwarg', 'var', 'ivar', 'cvar', 'raises', 'raise',
                      'except', 'exception']


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('field', SPHINX_NAME_FIELDS)
def test_sphinx_info_fields_preserve_the_name_they_carry(words, mode, field):
    source = docstring('    :' + field + ' color: The behavior.')
    assert PythonStrategy(mode).process(source, words)[0] == source.replace(
        'The behavior', 'The behaviour')


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('line', [
    ':type center: color',
    ':vartype center: color',
    ':rtype: color',
])
def test_sphinx_type_fields_protect_their_payload(words, mode, line):
    # These three carry a type expression rather than a description.
    assert PythonStrategy(mode).process(docstring('    ' + line), words)[0] == docstring('    ' + line)


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('line,corrected', [
    (':returns: the color of it', ':returns: the colour of it'),
    (':raises ValueError: bad color', ':raises ValueError: bad colour'),
    (':rtypes: the color', ':rtypes: the colour'),
    (':paramount color: the color', ':paramount colour: the colour'),
])
def test_sphinx_descriptions_and_unknown_fields_are_still_corrected(words, mode, line, corrected):
    source = docstring('    ' + line)
    assert PythonStrategy(mode).process(source, words)[0] == source.replace(line, corrected)


NUMPY_BODY = (
    '    Parameters\n'
    '    ----------\n'
    '    color\n'
    '        Whether the value is analyzed.\n'
    '    center, behavior : str\n'
    '        The mode was organized.\n'
    '    **color : dict\n'
    '        Extra options to finalize.\n'
    '\n'
    '    Returns\n'
    '    -------\n'
    '    center\n'
    '        The organized result.\n'
    '\n'
    '    Notes\n'
    '    -----\n'
    '    finalize\n'
    '        Not a parameter, so this line is analyzed prose.'
)


@pytest.mark.parametrize('mode', MODES)
def test_numpy_name_lines_preserved_and_descriptions_corrected(words, mode):
    source = docstring(NUMPY_BODY)
    # Every description is corrected; the name lines, and the Notes line that
    # only looks like one, are the difference.
    expected = (source.replace('analyzed', 'analysed').replace('organized', 'organised')
                .replace('finalize', 'finalise'))
    assert PythonStrategy(mode).process(source, words)[0] == expected


@pytest.mark.parametrize('mode', MODES)
def test_numpy_names_need_a_dashed_underline(words, mode):
    source = docstring('    Parameters\n\n    color\n        The color.')
    assert PythonStrategy(mode).process(source, words)[0] == source.replace('color', 'colour')


@pytest.mark.parametrize('mode', MODES)
def test_numpy_labels_survive_crlf(words, mode):
    source = docstring(NUMPY_BODY).replace('\n', '\r\n')
    result = PythonStrategy(mode).process(source, words)[0]
    assert '\r\n    color\r\n' in result
    assert '\r\n    center, behavior : str\r\n' in result
    assert 'Whether the value is analysed.' in result


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('line,corrected', [
    ('See also: the color table.', 'See also: the colour table.'),
    ('The color of the following:', 'The colour of the following:'),
    ('Warning: color was analyzed.', 'Warning: colour was analysed.'),
])
def test_prose_is_not_read_as_a_label(words, mode, line, corrected):
    source = docstring('    ' + line)
    assert PythonStrategy(mode).process(source, words)[0] == source.replace(line, corrected)


HARVESTED = '''def f(**kwargs):
    """Doc.

    Args:
        color: Enable output.
        value: Alias for color.

    The color option is analyzed on the way in.
    """
    # The color and the behavior are organized elsewhere.
'''


@pytest.mark.parametrize('mode', MODES)
def test_documented_names_protect_prose_across_the_file(words, mode):
    # A documented name is code, so it is protected in later prose and in
    # comments, not only on the label line that documents it.
    expected = (HARVESTED.replace('analyzed', 'analysed').replace('organized', 'organised')
                .replace('behavior', 'behaviour'))
    assert PythonStrategy(mode).process(HARVESTED, words)[0] == expected


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('label', [
    '    Args:\n        color: Enable it.',
    '    Args:\n        color (bool): Enable it.',
    '    :param color: Enable it.',
    '    :param bool color: Enable it.',
    '    :ivar color: Enable it.',
    '    :type color: bool',
    '    Parameters\n    ----------\n    color\n        Enable it.',
    '    Parameters\n    ----------\n    center, color : str\n        Enable it.',
])
def test_every_label_form_contributes_a_protected_name(words, mode, label):
    source = docstring(label) + '# The color was analyzed.\n'
    assert PythonStrategy(mode).process(source, words)[0] == source.replace(
        'analyzed', 'analysed')


@pytest.mark.parametrize('mode', MODES)
def test_only_documented_names_are_harvested(words, mode):
    # "Note:" is a label by shape, so "Note" is harvested and "behavior" is
    # not: an undocumented word in the same file keeps its correction.
    source = docstring('    Note: the behavior is analyzed.')
    assert PythonStrategy(mode).process(source, words)[0] == source.replace(
        'the behavior is analyzed', 'the behaviour is analysed')
