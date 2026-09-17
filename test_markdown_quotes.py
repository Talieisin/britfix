import copy
import io
import json
import time

import pytest

import britfix_core as core
from britfix_spans import quotation_spans

MAPPING = {'color': 'colour', 'flavor': 'flavour', 'behavior': 'behaviour'}


def markdown(source, monkeypatch=None, enabled=False):
    """Run the Markdown strategy, optionally with quoted-prose preservation on."""
    if monkeypatch is not None:
        monkeypatch.setitem(core._CONFIG['strategies']['markdown'], 'preserve_quoted_prose', enabled)
    return core.MarkdownStrategy().process(source, core.SpellingCorrector(MAPPING))[0]


@pytest.mark.parametrize('quote', ['*"color"*', '_“color”_', "*'color'*", '*“color”*'])
def test_explicit_italic_quote_default(quote):
    corrector = core.SpellingCorrector({'color': 'colour'})
    assert core.MarkdownStrategy().process(f'color {quote}', corrector)[0] == f'colour {quote}'


@pytest.mark.parametrize('enabled', [False, True])
def test_plain_quotation_policy(monkeypatch, enabled):
    monkeypatch.setitem(core._CONFIG['strategies']['markdown'], 'preserve_quoted_prose', enabled)
    source = 'color "color" and ‘color’ and \'color\''
    expected = source.replace('color', 'colour') if not enabled else 'colour "color" and ‘color’ and \'color\''
    corrector = core.SpellingCorrector({'color': 'colour'})
    strategy = core.MarkdownStrategy()
    assert strategy.process(source, corrector)[0] == expected
    assert len(strategy.find_safe_replacements(source, corrector)) == (1 if enabled else 4)


@pytest.mark.parametrize('source', ["'80s color", "'cause color", "users' color", "don't color", "'cause users' color"])
def test_apostrophes_do_not_mask_prose(monkeypatch, source):
    monkeypatch.setitem(core._CONFIG['strategies']['markdown'], 'preserve_quoted_prose', True)
    corrector = core.SpellingCorrector({'color': 'colour'})
    assert core.MarkdownStrategy().process(source, corrector)[0] == source.replace('color', 'colour')


def test_unclosed_quote_stops_at_crlf_paragraph(monkeypatch):
    monkeypatch.setitem(core._CONFIG['strategies']['markdown'], 'preserve_quoted_prose', True)
    corrector = core.SpellingCorrector({'color': 'colour'})
    source = 'color "color\r\ncolor\r\n\r\ncolor'
    assert core.MarkdownStrategy().process(source, corrector)[0] == 'colour "color\r\ncolor\r\n\r\ncolour'


@pytest.mark.parametrize('value', ['true', 1, None])
def test_non_boolean_policy_rejected(monkeypatch, value):
    config = copy.deepcopy(core._CONFIG)
    config['strategies']['markdown']['preserve_quoted_prose'] = value
    monkeypatch.setattr('builtins.open', lambda *a, **k: io.StringIO(json.dumps(config)))
    with pytest.raises(core.ConfigError, match='must be a boolean'):
        core._load_config()


@pytest.mark.parametrize('source', [
    'Set include to "src/*" and the color to "**/test" for flavor.',
    'Use "*" for color or "**" for flavor',
    '"foo_" and the color of "_bar" here',
    'Use `"src/*"` for the color and `"**/*.md"` for flavor',
    "| '*' | Any behavior; use '**' for flavor |",
    'Globs `"a/*"` then color and `"*/b"` then flavor',
])
def test_delimiters_in_paths_do_not_protect_prose(source):
    """A '*' or '_' that belongs to a glob never opens an emphasised quotation."""
    expected = source.replace('color', 'colour').replace('flavor', 'flavour')
    assert markdown(source) == expected.replace('behavior', 'behaviour')


@pytest.mark.parametrize('quote', ['**"color"**', '__"color"__', '***"color"***', '**“color”**'])
def test_bold_quotations_are_preserved_whole(quote):
    """Bold quotations stay verbatim, and the whole delimiter run is preserved."""
    assert markdown(f'{quote} and color') == f'{quote} and colour'


@pytest.mark.parametrize('source', ['**"color"* and color', '*"color"** and color', '*"color"_ and color'])
def test_unequal_or_mixed_delimiter_runs_protect_nothing(source):
    assert markdown(source) == source.replace('color', 'colour')


@pytest.mark.parametrize('source', ['(*"color"*) and color', '[*"color"*] and color', '“*"color"*” and color'])
def test_opening_punctuation_may_precede_the_delimiter(source):
    assert markdown(source) == source.replace(' color', ' colour')


@pytest.mark.parametrize('source', ['x/*"color"* and color', 'x*"color"* and color'])
def test_delimiter_glued_to_a_word_or_path_protects_nothing(source):
    assert markdown(source) == source.replace('color', 'colour')


def test_quotations_inside_code_are_not_scanned():
    source = 'Inline `*"color"*` and fenced:\n\n```\n*"color"* color\n```\n\ncolor after'
    assert markdown(source) == source.replace('color after', 'colour after')


def test_quotation_may_contain_a_whole_code_span():
    source = 'A *"color and `color` here"* then color'
    assert markdown(source) == 'A *"color and `color` here"* then colour'


def test_quotation_never_covers_part_of_a_code_span():
    source = 'a *"color` and `color"* color here'
    result = markdown(source)
    assert result.count('`') == source.count('`')
    assert result.endswith('colour here')


def test_unclosed_quote_stops_at_a_code_fence(monkeypatch):
    source = 'color "color\n```\ncolor\n```\ncolor'
    assert markdown(source, monkeypatch, True) == 'colour "color\n```\ncolor\n```\ncolour'


@pytest.mark.parametrize('source', ['‘Tis a color', '‘cause color', '‘90s color'])
def test_curly_elisions_do_not_mask_prose(monkeypatch, source):
    assert markdown(source, monkeypatch, True) == source.replace('color', 'colour')


@pytest.mark.parametrize('all_quotes', [False, True])
def test_dense_paragraph_scans_in_linear_time(all_quotes):
    """A paragraph dense with quotation marks must not cost quadratic time."""
    line = ' '.join(['some "quoted" words here'] * 40)
    text = '\n'.join([line] * 200)
    assert len(text) > 160_000
    start = time.perf_counter()
    quotation_spans(text, all_quotes)
    assert time.perf_counter() - start < 2.0


@pytest.mark.parametrize('quote', ['_*"color"*_', '**_"color"_**', '*__"color"__*', '***"color"***'])
def test_quotations_nested_in_emphasis_are_preserved(quote):
    """The other emphasis delimiter may precede an opening run."""
    assert markdown(f'{quote} and color') == f'{quote} and colour'


@pytest.mark.parametrize('source', ['x*"color"* and color', 'x/*"color"* and color', 'a1_"color"_ and color'])
def test_delimiter_after_a_word_or_path_still_protects_nothing(source):
    assert markdown(source) == source.replace('color', 'colour')


@pytest.mark.parametrize('source', ['*“color flavor ' * 2000, '_“' * 8000, '\'color ' * 8000])
def test_openers_that_never_close_scan_once(source):
    """An opener with no closing mark must not rescan its paragraph each time."""
    start = time.perf_counter()
    quotation_spans(source, False)
    quotation_spans(source, True)
    assert time.perf_counter() - start < 5.0
