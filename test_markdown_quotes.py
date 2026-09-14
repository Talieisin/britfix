import copy
import io
import json

import pytest

import britfix_core as core


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
