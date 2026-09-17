import os
import re
import subprocess
import sys
import time

import pytest

from britfix_core import MarkdownStrategy, SpellingCorrector
from britfix_spans import markdown_spans, mask_spans


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


# --- Code, bounds, definitions and masking ---------------------------------

TICK = chr(96)
FENCE = TICK * 3


def _process(corrector, source):
    return MarkdownStrategy().process(source, corrector)[0]


@pytest.mark.parametrize('opener', ['<script>', '<style>', '<!--', '<script src="x.js">'])
def test_markup_opener_inside_inline_code_does_not_swallow(corrector, opener):
    source = f'Add a {TICK}{opener}{TICK} tag. The color is nice.\nMore behavior here.\n'
    assert _process(corrector, source) == source.replace('color', 'colour').replace('behavior', 'behaviour')


@pytest.mark.parametrize('block', [
    f'{FENCE}html\n<!-- open\n{FENCE}\n',
    f'{FENCE}\n<script>\n{FENCE}\n',
    '    <!-- open\n',
    '> <style> quoted\n',
])
def test_markup_opener_inside_code_block_does_not_swallow(corrector, block):
    source = f'{block}\nThe color is nice.\n'
    assert _process(corrector, source) == f'{block}\nThe colour is nice.\n'


@pytest.mark.parametrize('opener', ['<!-- draft', '<script>', '<style>'])
@pytest.mark.parametrize('prefix', ['', 'Some color text ', '   '])
def test_unclosed_markup_is_bounded_to_its_paragraph(corrector, prefix, opener):
    source = f'{prefix}{opener} color\nbehavior\n\nThe color after.\n'
    expected_prefix = prefix.replace('color', 'colour')
    expected = f'{expected_prefix}{opener} color\nbehavior\n\nThe colour after.\n'
    assert _process(corrector, source) == expected


def test_unclosed_markup_stops_before_a_fence(corrector):
    source = f'Text <!-- note color\n{FENCE}\ncode color\n{FENCE}\nbehavior\n'
    assert _process(corrector, source) == source.replace('\nbehavior', '\nbehaviour')


def test_unclosed_markup_stops_before_a_backtick(corrector):
    source = f'<!-- note color {TICK}code color{TICK} behavior\n'
    assert _process(corrector, source) == f'<!-- note color {TICK}code color{TICK} behaviour\n'


def test_line_start_comment_with_closer_spans_paragraphs(corrector):
    source = '<!--\n## Draft color\n\nbehavior text\n\n-->\nThe color after.\n'
    assert _process(corrector, source) == source.replace('The color', 'The colour')


def test_line_start_script_with_closer_spans_paragraphs(corrector):
    source = '<script>\nconst color = 1;\n\nlet behavior;\n</script>\nThe color after.\n'
    assert _process(corrector, source) == source.replace('The color', 'The colour')


def test_inline_comment_does_not_pair_with_closer_after_blank_line(corrector):
    source = 'Text <!-- color\n\nbehavior -->\n'
    assert _process(corrector, source) == 'Text <!-- color\n\nbehaviour -->\n'


def test_tag_does_not_span_a_blank_line(corrector):
    # Only the core's own tag split still applies, as on main.
    source = "a <b title='x\n\ncolor > behavior' c>\n"
    assert _process(corrector, source) == "a <b title='x\n\ncolor > behaviour' c>\n"


def test_footnote_text_is_prose_and_label_is_kept(corrector):
    source = 'Text[^color-note] color.\n\n[^color-note]: The footnote color is behavior.\nMore color.\n'
    expected = ('Text[^color-note] colour.\n\n'
                '[^color-note]: The footnote colour is behaviour.\nMore colour.\n')
    assert _process(corrector, source) == expected


@pytest.mark.parametrize('line', [
    '[Note]: this color sentence is not a real definition',
    '[color]: ../behavior trailing color words',
    '[color]:',
    '[]: ../behavior',
])
def test_lines_that_are_not_definitions_are_prose(corrector, line):
    source = line + '\n'
    assert _process(corrector, source) == source.replace('color', 'colour').replace('behavior', 'behaviour')


@pytest.mark.parametrize('definition', [
    '[color]: ../behavior',
    '[color]: <../color behavior> "color title"',
    "[color]: ../behavior 'color title'",
    '[color]: ../behavior (color title)',
    '[color]:\n  ../behavior\n  "color\n  title"',
    '   [color]: ../behavior',
])
def test_valid_definitions_keep_label_destination_and_title(corrector, definition):
    source = f'The color [color].\n\n{definition}\nbehavior after\n'
    expected = f'The colour [color].\n\n{definition}\nbehaviour after\n'
    assert _process(corrector, source) == expected


def test_definition_title_line_that_is_prose_ends_the_definition(corrector):
    source = '[color]: ../behavior\n"color" is a word.\n'
    assert _process(corrector, source) == '[color]: ../behavior\n"colour" is a word.\n'


def test_definition_inside_fence_is_not_a_definition(corrector):
    source = f'{FENCE}\n[color]: ../behavior\n{FENCE}\n\nSee [color].\n'
    assert _process(corrector, source) == source.replace('See [color]', 'See [colour]')


def test_text_after_multiline_markup_is_not_indented_code(corrector):
    source = '<!-- comment\n-->    color here\n'
    assert _process(corrector, source) == '<!-- comment\n-->    colour here\n'


def test_destination_never_hides_part_of_inline_code(corrector):
    source = f'[a](x {TICK}y) color {TICK} behavior\n'
    assert _process(corrector, source) == f'[a](x {TICK}y) color {TICK} behaviour\n'


@pytest.mark.parametrize('source', [
    'a <!-- x\r\ny --> b\r\n',
    'a <!-- x\r\n\r\n-->\r\nb',
    'a <!-- x\ry -->\rb',
    '<!--\n\n-->',
    'a https://x.org/p\n<script>\r\nq\r\n</script>',
    'x <b\ntitle="y\r\nz">',
])
def test_mask_restore_round_trips_multiline_spans(source):
    spans = markdown_spans(source)
    masked, restore = mask_spans(source, spans)
    assert '\x00' in masked
    assert restore(masked) == source
    # Line structure outside the spans is unchanged.
    assert masked.count('\n') == source.count('\n')
    assert masked.count('\r') == source.count('\r')


def test_mask_restore_round_trips_every_span_shape():
    source = 'ab\r\ncd\nef\rgh'
    for start in range(len(source)):
        for end in range(start + 1, len(source) + 1):
            masked, restore = mask_spans(source, [(start, end)])
            assert restore(masked) == source


def test_spans_module_imports_alone_without_a_cycle():
    code = (
        'import britfix_spans\n'
        'assert britfix_spans.markdown_spans("[a]: /b")\n'
        'import britfix_core\n'
    )
    subprocess.run([sys.executable, '-c', code], check=True, cwd=os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.parametrize('line', [
    'see figure [{} color and behavior text',
    'see [link {}](open color and behavior text',
    'see <b title="{} color and behavior text',
    'see {} <!-- color and ' + TICK + ' behavior text',
])
def test_unmatched_syntax_scans_linearly(line):
    source = '\n'.join(line.format(i) for i in range(3000)) + '\n'
    started = time.perf_counter()
    markdown_spans(source)
    assert time.perf_counter() - started < 5.0


def test_url_glued_to_a_word_is_not_masked(corrector):
    source = 'COLORhttp://x.com/color and color'
    assert _process(corrector, source) == 'COLORhttp://x.com/colour and colour'


def test_restore_is_linear_in_span_count():
    source = 'word <b>x</b> ' * 50000
    spans = [(m.start(), m.end()) for m in re.finditer(r'<[^>]*>', source)]
    masked, restore = mask_spans(source, spans)
    started = time.perf_counter()
    assert restore(masked) == source
    assert time.perf_counter() - started < 5.0


def test_restore_leaves_a_damaged_token_as_found():
    source = 'a <!-- x\ny --> b'
    masked, restore = mask_spans(source, [(2, 14)])
    damaged = masked.replace('\n', '\n\n')
    assert restore(damaged) == damaged


def test_mask_restore_round_trips_a_source_containing_nul(corrector):
    source = 'a \x00 <!-- x\ny --> \x001\x00 color\n'
    masked, restore = mask_spans(source, markdown_spans(source))
    assert restore(masked) == source
    assert _process(corrector, source) == source.replace(' color', ' colour')
