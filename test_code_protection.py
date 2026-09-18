"""Technical references in comments survive in every code and stylesheet file.

Issue #63: a comment referring to the Python API `xref.finalize` was rewritten
to `xref.finalise`, leaving the comment pointing at a function that does not
exist. PythonStrategy protects dotted names and backtick spans in .py sources;
these tests lock the same protection into CodeStrategy and CssStrategy.
"""

import pytest

import britfix_core as core

CODE_EXTENSIONS = ['.ts', '.js', '.jsx', '.tsx', '.rb', '.go', '.rs', '.sh', '.java']
STYLE_EXTENSIONS = ['.css', '.scss']


@pytest.fixture
def corrector():
    return core.SpellingCorrector({
        'color': 'colour', 'behavior': 'behaviour',
        'finalize': 'finalise', 'center': 'centre', 'analyze': 'analyse',
    })


@pytest.mark.parametrize('extension', CODE_EXTENSIONS)
@pytest.mark.parametrize('comment', ['// {}', '/* {} */', '# {}'])
def test_dotted_name_survives_beside_corrected_prose(corrector, extension, comment):
    source = comment.format('The color is nice; see xref.finalize')
    expected = comment.format('The colour is nice; see xref.finalize')
    strategy = core.get_file_strategy(extension)
    result, counts = strategy.process(source, corrector)
    assert result == expected
    assert counts == {'color': 1}


@pytest.mark.parametrize('extension', STYLE_EXTENSIONS)
def test_dotted_name_survives_in_stylesheet_comment(corrector, extension):
    source = '/* The color is nice; see theme.finalize */\n.a { color: red; }\n'
    strategy = core.get_file_strategy(extension)
    result, counts = strategy.process(source, corrector)
    assert result == source.replace('The color', 'The colour')
    assert counts == {'color': 1}


@pytest.mark.parametrize('reference', [
    'xref.finalize', 'Palette.set_color', 'obj.center()', 'config.color',
    'a.b.color', 'theme.color.value', 'color.ts',
])
@pytest.mark.parametrize('extension', ['.ts', '.go', '.css'])
def test_dotted_forms_are_left_alone(corrector, reference, extension):
    source = f'/* Read {reference} before the color changes */'
    strategy = core.get_file_strategy(extension)
    result, counts = strategy.process(source, corrector)
    assert result == f'/* Read {reference} before the colour changes */'
    assert counts == {'color': 1}


@pytest.mark.parametrize('span', ['`color`', '``behavior``', '`` `color` ``'])
@pytest.mark.parametrize('extension', ['.ts', '.rb', '.scss'])
def test_backtick_spans_are_left_alone(corrector, span, extension):
    source = f'/* Use {span} for the color */'
    strategy = core.get_file_strategy(extension)
    result, counts = strategy.process(source, corrector)
    assert result == f'/* Use {span} for the colour */'
    assert counts == {'color': 1}


@pytest.mark.parametrize('extension', ['.ts', '.sh', '.css'])
def test_quoted_run_and_contraction_compose_with_protection(corrector, extension):
    source = "/* It's the 'colorScheme' of xref.finalize that's the wrong color */"
    strategy = core.get_file_strategy(extension)
    result, counts = strategy.process(source, corrector)
    assert result == source.replace('wrong color', 'wrong colour')
    assert counts == {'color': 1}


@pytest.mark.parametrize('extension', ['.ts', '.js', '.go'])
def test_string_literals_are_still_skipped(corrector, extension):
    source = 'const value = "color";\nconfig.get(\'behavior\');\n// the color\n'
    strategy = core.get_file_strategy(extension)
    result, counts = strategy.process(source, corrector)
    assert result == source.replace('// the color', '// the colour')
    assert counts == {'color': 1}


@pytest.mark.parametrize('extension', ['.ts', '.rb'])
def test_decimal_numbers_are_protected_and_prose_still_corrected(corrector, extension):
    source = '// version 1.5 of the library has better behavior'
    strategy = core.get_file_strategy(extension)
    result, counts = strategy.process(source, corrector)
    assert result == '// version 1.5 of the library has better behaviour'
    assert counts == {'behavior': 1}


@pytest.mark.parametrize('extension', ['.ts', '.java', '.css'])
def test_prose_in_the_same_comment_is_still_corrected(corrector, extension):
    source = '/* xref.finalize will analyze the color and center of the behavior */'
    strategy = core.get_file_strategy(extension)
    result, counts = strategy.process(source, corrector)
    assert result == ('/* xref.finalize will analyse the colour and centre '
                      'of the behaviour */')
    assert counts == {'analyze': 1, 'color': 1, 'center': 1, 'behavior': 1}


@pytest.mark.parametrize('extension', CODE_EXTENSIONS + STYLE_EXTENSIONS)
def test_interactive_replacements_match_processing(corrector, extension):
    source = '/* xref.finalize sets the color of the behavior */'
    strategy = core.get_file_strategy(extension)
    replacements = strategy.find_safe_replacements(source, corrector)
    assert [old for _, _, old, _ in replacements] == ['color', 'behavior']


def test_python_files_keep_their_own_strategy(corrector):
    source = ('import xref\n\n\n'
              'def build():\n'
              '    # Call xref.finalize before saving.\n'
              '    xref.finalize()\n')
    assert not isinstance(core.get_file_strategy('.py'), core.CodeStrategy)
    assert core.get_file_strategy('.py').process(source, corrector)[0] == source


@pytest.mark.parametrize('text,start,expected', [
    ('`color`', 0, 7),
    ('``behavior``', 0, 12),
    ('`` `color` ``', 0, 13),
    ('`color and behavior', 0, 19),
    ('``color and behavior', 0, 20),
])
def test_backtick_span_end_boundaries(text, start, expected):
    assert core._backtick_span_end(text, start) == expected
