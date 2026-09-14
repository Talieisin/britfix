import pytest

from britfix_core import MarkdownStrategy, SpellingCorrector


@pytest.fixture
def corrector():
    return SpellingCorrector({'color': 'colour', 'behavior': 'behaviour'})


@pytest.mark.parametrize('protected', [
    'https://example.org/color?q=behavior#color',
    "https://example.org/it's-color?q=behavior",
    'https://example.org/color_(behavior)',
    '<https://example.org/color>',
    '[details](../color_(behavior) "color title")',
    '![details](../color_(behavior))',
    '<span title="color > behavior">',
    '<!-- color\nbehavior -->',
    '<script>const color = "behavior";</script>',
    '<style>.color { color: behavior; }</style>',
])
def test_protected_syntax_with_nearby_prose(corrector, protected):
    source = f'color prose {protected} behavior prose'
    result, counts = MarkdownStrategy().process(source, corrector)
    assert result == f'colour prose {protected} behaviour prose'
    assert counts == {'color': 1, 'behavior': 1}
    replacements = MarkdownStrategy().find_safe_replacements(source, corrector)
    assert len(replacements) == 2


@pytest.mark.parametrize('usage', [
    '[details][color]', '[color][]', '[color]',
    '![details][color]', '![color][]', '![color]',
])
def test_reference_identifiers_remain_linked(corrector, usage):
    source = f'color prose {usage}\n\n[color]: ../behavior "color"\n'
    result, _ = MarkdownStrategy().process(source, corrector)
    assert result == source.replace('color prose', 'colour prose')


def test_explicit_link_text_is_still_prose(corrector):
    source = '[color [behavior]](../color_(behavior)) color'
    result, _ = MarkdownStrategy().process(source, corrector)
    assert result == '[colour [behaviour]](../color_(behavior)) colour'


def test_reference_continuation_and_label_normalisation(corrector):
    source = '[details][Color Behavior] color\n\n[color   behavior]:\n  ../color\n  "behavior"\n'
    result, _ = MarkdownStrategy().process(source, corrector)
    assert result == source.replace('] color\n', '] colour\n')


def test_unclosed_markup_is_preserved(corrector):
    source = 'color\n<script>behavior\ncolor'
    assert MarkdownStrategy().process(source, corrector)[0] == 'colour\n<script>behavior\ncolor'


def test_existing_code_syntax_remains_preserved(corrector):
    source = 'color\n```\nhttps://example.org/color\nbehavior\n```\nbehavior'
    expected = 'colour\n```\nhttps://example.org/color\nbehavior\n```\nbehaviour'
    assert MarkdownStrategy().process(source, corrector)[0] == expected
