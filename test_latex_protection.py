import subprocess
import sys
from pathlib import Path

import pytest

import britfix
from britfix_core import LaTeXStrategy, SpellingCorrector


@pytest.fixture
def corrector():
    return SpellingCorrector({'color': 'colour', 'behavior': 'behaviour'})


@pytest.mark.parametrize('protected', [
    r'\color{color}', r'\label{behavior}', r'\cite[color]{behavior}',
    r'\input{color}', r'\unknown{color {behavior}}', r'\url{https://example.org/color}',
    r'$color$', r'$$color$$', r'\(color\)', r'\[behavior\]',
    r'\begin{equation}color\end{equation}',
    r'\begin{align*}color\end{align*}',
    r'\begin{verbatim}color\end{verbatim}',
    r'\begin{lstlisting}color\end{lstlisting}',
    r'\begin{minted}{python}color\end{minted}',
    r'\verb|color|', r'\verb*|color|', r'\lstinline[language=C]|color|',
    r'\mintinline{python}|color|', r'\mintinline{python}{color}',
])
def test_syntax_protected_with_prose_control(corrector, protected):
    source = f'color {protected} behavior'
    strategy = LaTeXStrategy()
    result, counts = strategy.process(source, corrector)
    assert result == f'colour {protected} behaviour'
    assert counts == {'color': 1, 'behavior': 1}
    assert len(strategy.find_safe_replacements(source, corrector)) == 2


@pytest.mark.parametrize('macro', ['textbf', 'textit', 'emph', 'section', 'section*', 'caption', 'footnote'])
def test_known_prose_arguments_convert(corrector, macro):
    source = '\\' + macro + '[color]{color \\emph{behavior}}'
    expected = '\\' + macro + '[color]{colour \\emph{behaviour}}'
    assert LaTeXStrategy().process(source, corrector)[0] == expected


def test_href_argument_roles(corrector):
    source = r'\href{https://example.org/color}{color \emph{behavior}}'
    assert LaTeXStrategy().process(source, corrector)[0] == r'\href{https://example.org/color}{colour \emph{behaviour}}'


def test_comments_and_escaped_braces(corrector):
    source = 'color % behavior { $ not structural\n' + r'\textbf{color \{ behavior \}}'
    assert LaTeXStrategy().process(source, corrector)[0] == source.replace('color', 'colour').replace('behavior', 'behaviour')


@pytest.mark.parametrize('tail', [r'\unknown{color', '$color', r'\begin{minted}{python}color', r'\verb|color'])
def test_unterminated_region_preserves_remainder(corrector, tail):
    strategy = LaTeXStrategy()
    assert strategy.process('color ' + tail, corrector)[0] == 'colour ' + tail
    assert strategy.partial_skips


def test_partial_diagnostic_reaches_cli(tmp_path):
    path = tmp_path / 'input.tex'
    path.write_text('color $behavior')
    result = subprocess.run([sys.executable, str(Path(britfix.__file__)), '--input', str(path), '--no-backup'], capture_output=True, text=True)
    assert result.returncode == 0
    assert 'britfix: skipped ' in result.stderr
    assert 'partial: 1' in result.stdout
    assert path.read_text() == 'colour $behavior'


@pytest.mark.parametrize('inert_end', [r'% \end{equation}', r'\\end{equation}'])
def test_math_terminator_respects_comments_and_escapes(corrector, inert_end):
    equation = '\\begin{equation}\n' + inert_end + '\ncolor\n\\end{equation}'
    source = 'color ' + equation + ' behavior'
    strategy = LaTeXStrategy()
    assert strategy.process(source, corrector)[0] == 'colour ' + equation + ' behaviour'
    assert not strategy.partial_skips


def test_candidate_filter_matches_brute_force_overlap():
    import json as json_module
    import britfix_core as core
    from britfix_latex import latex_replacements, latex_spans
    corrector = core.SpellingCorrector(json_module.loads(Path(core.__file__).with_name('spelling-mapper.json').read_text()))
    pieces = [r'color \textbf{color}', r'\cite[color]{behavior}', '$color$', 'behavior',
              r'\href{https://example.org/color}{color}', '% color\n', r'\unknown{color}color', '\n\n']
    source = ' '.join(pieces[(k * 7) % len(pieces)] for k in range(400))
    spans, _ = latex_spans(source)
    expected = [r for r in corrector.find_replacements(source)
                if not any(a < r[1] and r[0] < b for a, b in spans)]
    assert latex_replacements(source, corrector)[0] == expected
    # A span ending exactly where a candidate starts does not hide it.
    assert LaTeXStrategy().process(r'\unknown{x}color', corrector)[0] == r'\unknown{x}colour'


QUOTED = [
    ('She said "the color is licensed" and left.', 'She said "the colour is licensed" and left.'),
    ('A 5" color monitor, then behavior.', 'A 5" colour monitor, then behaviour.'),
]


@pytest.mark.parametrize('source, expected', QUOTED)
def test_quoted_prose_corrected_by_default(corrector, source, expected):
    strategy = LaTeXStrategy()
    assert strategy.process(source, corrector)[0] == expected
    assert not strategy.partial_skips


def test_quoted_prose_preserved_when_enabled(monkeypatch, corrector):
    import britfix_core as core
    monkeypatch.setitem(core._CONFIG['strategies']['latex'], 'preserve_quoted_prose', True)
    source = 'color "color behavior" behavior'
    assert LaTeXStrategy().process(source, corrector)[0] == 'colour "color behavior" behaviour'


@pytest.mark.parametrize('value', ['true', 1, None])
def test_non_boolean_latex_quote_policy_rejected(monkeypatch, value):
    import copy
    import io
    import json as json_module
    import britfix_core as core
    config = copy.deepcopy(core._CONFIG)
    config['strategies']['latex']['preserve_quoted_prose'] = value
    monkeypatch.setattr('builtins.open', lambda *a, **k: io.StringIO(json_module.dumps(config)))
    with pytest.raises(core.ConfigError, match='latex.preserve_quoted_prose must be a boolean'):
        core._load_config()


@pytest.mark.parametrize('verbatim', [
    r'\url{https://example.org/a%20b}',
    r'\url{C:\temp\color}',
    r'\path{a%b\color}',
    r'\nolinkurl{a%b}',
    r'\href{https://example.org/?q=100%25}{color}',
    r'\href[pdfnewwindow]{https://example.org/%7Ecolor}{color}',
    r'\lstinline{printf("%d\n")}',
    r'\mintinline{c}{printf("%d\n")}',
])
def test_verbatim_arguments_keep_percent_and_backslash_literal(corrector, verbatim):
    source = verbatim + ' behavior\ncolor'
    expected = verbatim.replace('}{color}', '}{colour}') + ' behaviour\ncolour'
    strategy = LaTeXStrategy()
    assert strategy.process(source, corrector)[0] == expected
    assert not strategy.partial_skips


def test_percent_in_url_nested_in_argument_is_a_comment(corrector):
    # TeX has already tokenised the outer argument, so % starts a comment there
    # and the url package requires \%; the remainder stays preserved.
    source = 'color \\footnote{\\url{a%b}}\nbehavior'
    strategy = LaTeXStrategy()
    assert strategy.process(source, corrector)[0] == 'colour \\footnote{\\url{a%b}}\nbehavior'
    assert strategy.partial_skips


def test_moderate_nesting_still_converts(corrector):
    source = r'\textbf{' * 20 + 'color' + '}' * 20 + ' behavior'
    assert LaTeXStrategy().process(source, corrector)[0] == source.replace('color', 'colour').replace('behavior', 'behaviour')


def test_deep_nesting_preserves_remainder_without_error(corrector):
    source = 'color ' + r'\textbf{' * 3000 + 'color' + '}' * 3000 + ' behavior'
    strategy = LaTeXStrategy()
    result, _ = strategy.process(source, corrector)
    assert result == 'colour ' + source[len('color '):]
    assert strategy.partial_skips == ['LaTeX nesting too deep']
