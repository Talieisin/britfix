"""Verbatim spans used by spelling strategies; no document reserialisation."""

import bisect
import re
import unicodedata
import uuid


def merge_spans(spans):
    merged = []
    for start, end in sorted(spans):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def mask_spans(text, spans):
    """Mask by source offsets, retaining line breaks for surrounding syntax."""
    # Tokens are scanned by the corrector, so their length costs time on large
    # files. A NUL delimiter alone is enough when the source has none; failing
    # that, a random marker the source does not contain is added.
    prefix = '\x00'
    if prefix in text:
        marker = uuid.uuid4().hex[:8]
        while marker in text:
            marker = uuid.uuid4().hex[:8]
        prefix = f'\x00{marker}:'
    originals = []
    pieces = []
    pos = 0
    for start, end in merge_spans(spans):
        index = len(originals)
        original = text[start:end]
        breaks = ''.join(re.findall(r'\r\n|\r|\n', original))
        replacement = f'{prefix}{index}\x00' + breaks
        if breaks and not original.endswith(('\n', '\r')):
            # Text after a multi-line span keeps a non-blank line prefix, so
            # following spaces are not read as an indented code block.
            replacement += f'{prefix}{index}:e\x00'
        originals.append((replacement, original))
        pieces.extend((text[pos:start], replacement))
        pos = end
    pieces.append(text[pos:])

    token = re.compile(re.escape(prefix) + r'(\d+)\x00')

    def restore(result):
        # One pass: each leading token must be followed by the rest of its
        # replacement; anything else is left as found.
        pieces = []
        pos = 0
        search_from = 0
        while True:
            match = token.search(result, search_from)
            if not match:
                break
            start = match.start()
            index = int(match.group(1))
            if index < len(originals):
                replacement, original = originals[index]
                if result.startswith(replacement, start):
                    pieces.append(result[pos:start])
                    pieces.append(original)
                    pos = search_from = start + len(replacement)
                    continue
            search_from = match.end()
        pieces.append(result[pos:])
        return ''.join(pieces)

    return ''.join(pieces), restore


def balanced_end(text, start, opening='[', closing=']', limit=None):
    depth = 0
    i = start
    quote = None
    stop = len(text) if limit is None else min(limit, len(text))
    while i < stop:
        char = text[i]
        if char == '\\':
            i += 2
            continue
        # Quotes can contain parentheses in link titles.
        if opening == '(' and char in ('"', "'"):
            if quote == char:
                quote = None
            elif quote is None and (i == start + 1 or text[i - 1].isspace()):
                quote = char
        if quote is None:
            if char == opening:
                depth += 1
            elif char == closing:
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return None


def url_spans(text):
    spans = []
    for match in re.finditer(r'https?://[^\s<>"`]+', text, re.I):
        start, end = match.span()
        # A quote immediately before the URL can wrap it; apostrophes within
        # a URI are legal sub-delimiters and never terminate a bare URL.
        if start and text[start - 1] in "'\u2018\u201c":
            closing = {"'": "'", '\u2018': '\u2019', '\u201c': '\u201d'}[text[start - 1]]
            if text[start:end].endswith(closing):
                end -= 1
        while end > start and text[end - 1] in '.,;:!?':
            end -= 1
        for left, right in [('(', ')'), ('[', ']')]:
            while end > start and text[end - 1] == right and text[start:end].count(right) > text[start:end].count(left):
                end -= 1
        spans.append((start, end))
    return spans


class _Finder:
    """First match at or after a position, reusing the previous search.

    The scan only moves forwards, so a search that found nothing (or found a
    match at h) answers every later query up to h without rescanning.
    """

    def __init__(self, search):
        self._search = search
        self._from = None
        self._hit = None

    def __call__(self, pos):
        if self._from is not None and pos >= self._from:
            if self._hit is None:
                return None
            if pos <= self._hit[0]:
                return self._hit
        self._from = pos
        self._hit = self._search(pos)
        return self._hit


def _literal_finder(text, needle):
    def search(pos):
        index = text.find(needle, pos)
        return None if index < 0 else (index, index + len(needle))
    return _Finder(search)


def _regex_finder(text, pattern):
    def search(pos):
        match = pattern.search(text, pos)
        return match.span() if match else None
    return _Finder(search)


# A paragraph ends before a blank line or a column-0 code fence.
_BOUNDARY = re.compile(r'^(?:[ \t\r]*$|```|~~~)', re.M)
_STRUCTURE = re.compile(r'`+|<|\n')
_ATTRS = r'(?:[^<>"\']|"[^"]*"|\'[^\']*\')*'
_TAG = re.compile(r'</?[A-Za-z]' + _ATTRS + '>')
_RAW_OPEN = re.compile(r'<(script|style)\b' + _ATTRS + '>', re.I)
_RAW_CLOSE = {
    'script': re.compile(r'</script\s*>', re.I),
    'style': re.compile(r'</style\s*>', re.I),
}
_DEFINITION_START = re.compile(r' {0,3}\[')
_BRACKET = re.compile(r'\\[\s\S]|[\[\]]')


def _skip_space(text, i, newline=True):
    n = len(text)
    while i < n and text[i] in ' \t':
        i += 1
    if newline and i < n and text[i] in '\r\n':
        i += 2 if text.startswith('\r\n', i) else 1
        while i < n and text[i] in ' \t':
            i += 1
    return i


def _label_close(text, i, limit):
    """Index of the ']' closing a reference label opened before i, or None."""
    stop = min(limit, i + 1000)
    while i < stop:
        char = text[i]
        if char == '\\':
            i += 2
        elif char == '[':
            return None
        elif char == ']':
            return i
        else:
            i += 1
    return None


def _destination_end(text, i):
    n = len(text)
    if i >= n:
        return None
    if text[i] == '<':
        j = i + 1
        while j < n:
            char = text[j]
            if char == '\\' and j + 1 < n and text[j + 1] not in '\r\n':
                j += 2
            elif char in '\r\n<':
                return None
            elif char == '>':
                return j + 1
            else:
                j += 1
        return None
    depth = 0
    j = i
    while j < n:
        char = text[j]
        if char == '\\' and j + 1 < n and not text[j + 1].isspace():
            j += 2
            continue
        if char.isspace() or ord(char) < 32:
            break
        if char == '(':
            depth += 1
        elif char == ')':
            if depth == 0:
                break
            depth -= 1
        j += 1
    if j == i or depth:
        return None
    return j


def _title_end(text, i, limit):
    closing = {'"': '"', "'": "'", '(': ')'}.get(text[i:i + 1])
    if closing is None:
        return None
    j = i + 1
    while j < limit:
        char = text[j]
        if char == '\\':
            j += 2
        elif char == closing:
            return j + 1
        elif closing == ')' and char == '(':
            return None
        else:
            j += 1
    return None


def _definition(text, pos, paragraph_end):
    """Parse a footnote or link reference definition starting a line.

    Returns (label, protected spans, resume offset) or None when the line is
    not a definition, in which case it stays prose.
    """
    match = _DEFINITION_START.match(text, pos)
    if not match:
        return None
    opening = match.end() - 1
    close = _label_close(text, opening + 1, paragraph_end(opening))
    if close is None or text[close + 1:close + 2] != ':':
        return None
    raw_label = text[opening + 1:close]
    if not raw_label.strip():
        return None
    label = normalise_label(raw_label)
    label_span = (opening, close + 2)
    if raw_label.startswith('^'):
        # Footnote: only the identity is syntax; the note itself is prose.
        return label, [label_span], close + 2

    n = len(text)
    dest_start = _skip_space(text, close + 2)
    dest_end = _destination_end(text, dest_start)
    if dest_end is None:
        return None
    line_rest = _skip_space(text, dest_end, newline=False)
    at_line_end = line_rest >= n or text[line_rest] in '\r\n'

    title_start = _skip_space(text, dest_end)
    if title_start > dest_end and title_start < n:
        title_end = _title_end(text, title_start, paragraph_end(title_start))
        if title_end is not None:
            after = _skip_space(text, title_end, newline=False)
            if after >= n or text[after] in '\r\n':
                spans = [label_span, (dest_start, dest_end), (title_start, title_end)]
                return label, spans, after
    if at_line_end:
        return label, [label_span, (dest_start, dest_end)], line_rest
    return None


def _code_block_end(markdown, text, pos):
    """End of a code block or blockquote line starting at pos, as core sees it."""
    n = len(text)
    char = text[pos]
    if char in '`~':
        fence_len = markdown._count_fence_chars(text, pos, char)
        if fence_len >= 3:
            line_end = text.find('\n', pos)
            if line_end == -1:
                return n
            close = markdown._find_closing_fence(text, line_end + 1, char, fence_len)
            if close == -1:
                return n
            close_end = text.find('\n', close + 1)
            return n if close_end == -1 else close_end + 1
    if text.startswith('    ', pos) or char == '\t':
        return markdown._find_indented_block_end(text, pos)
    if markdown._line_is_blockquote(text, pos):
        line_end = text.find('\n', pos)
        return n if line_end == -1 else line_end + 1
    return None


def markdown_spans(text):
    # Code detection reuses the Markdown strategy's own rules so the masked
    # regions agree with what it later preserves. Imported lazily because
    # britfix_core imports this module.
    from britfix_core import MarkdownStrategy

    markdown = MarkdownStrategy()
    n = len(text)
    boundaries = [max(m.start() - 1, 0) for m in _BOUNDARY.finditer(text)] + [n]

    def paragraph_end(pos):
        return boundaries[bisect.bisect_right(boundaries, pos)] if pos < n else n

    # A URL glued to a preceding word is not an autolink; masking it would
    # also split that word at a new boundary.
    spans = [span for span in url_spans(text) if not (span[0] and text[span[0] - 1].isalnum())]
    code = []
    structural = []
    definitions = set()
    backticks = {}
    comment_close = _literal_finder(text, '-->')
    raw_close = {name: _regex_finder(text, pattern) for name, pattern in _RAW_CLOSE.items()}

    def markup_end(p):
        # Up to three spaces of indentation make this an HTML block, which
        # may run across blank lines to its closer; inline HTML may not.
        j = p
        while j > 0 and p - j < 4 and text[j - 1] == ' ':
            j -= 1
        block = p - j <= 3 and (j == 0 or text[j - 1] == '\n')
        limit = paragraph_end(p)
        if text.startswith('<!--', p):
            hit = comment_close(p + 2)
        else:
            match = _RAW_OPEN.match(text, p, limit)
            if not match:
                match = _TAG.match(text, p, limit)
                return match.end() if match else None
            hit = raw_close[match.group(1).lower()](match.end())
        if hit and (block or hit[1] <= limit):
            return hit[1]
        # Unclosed: protect to the end of the paragraph, never the file, and
        # stop before any backtick so code pairing is left untouched.
        tick = text.find('`', p, limit)
        return limit if tick == -1 else tick

    pos = 0
    while pos < n:
        if pos == 0 or text[pos - 1] == '\n':
            end = _code_block_end(markdown, text, pos)
            if end is not None:
                code.append((pos, end))
                pos = end
                continue
            parsed = _definition(text, pos, paragraph_end)
            if parsed:
                label, found, resume = parsed
                definitions.add(label)
                structural.extend(found)
                pos = resume
                continue
        match = _STRUCTURE.search(text, pos)
        if not match:
            break
        p = match.start()
        char = text[p]
        if char == '\n':
            pos = p + 1
        elif char == '`':
            run = match.end() - p
            if run not in backticks:
                backticks[run] = _literal_finder(text, '`' * run)
            hit = backticks[run](p + run)
            if hit is None:
                # As in the strategy: step one backtick and retry shorter runs.
                pos = p + 1
            else:
                code.append((p, hit[1]))
                pos = hit[1]
        else:
            end = markup_end(p)
            if end is None:
                pos = p + 1
            else:
                structural.append((p, end))
                pos = end
    spans.extend(structural)

    # Pair brackets in one pass outside code, markup and definitions.
    excluded = merge_spans(code + structural)
    close = {}
    stack = []
    ex = 0
    boundary = 0
    for match in _BRACKET.finditer(text):
        p = match.start()
        while ex < len(excluded) and excluded[ex][1] <= p:
            ex += 1
        if ex < len(excluded) and excluded[ex][0] <= p:
            continue
        if boundaries[boundary] < p:
            while boundaries[boundary] < p:
                boundary += 1
            stack.clear()
        token = match.group()
        if token == '[':
            stack.append(p)
        elif token == ']' and stack:
            close[stack.pop()] = p + 1

    code_starts = [start for start, _ in code]

    def add(start, end):
        # Never mask part of a code region: hiding one backtick would change
        # how the strategy pairs the rest.
        k = bisect.bisect_right(code_starts, start) - 1
        if k >= 0 and code_starts[k] < start < code[k][1]:
            return
        k = bisect.bisect_left(code_starts, end) - 1
        if k >= 0 and code_starts[k] >= start and code[k][1] > end:
            return
        spans.append((start, end))

    i = 0
    for opening in sorted(close):
        if opening < i:
            continue
        end = close[opening]
        label = normalise_label(text[opening + 1:end - 1])
        if text[end:end + 1] == '(':
            line_end = text.find('\n', end)
            next_end = n if line_end == -1 else text.find('\n', line_end + 1)
            limit = min(paragraph_end(end), n if next_end == -1 else next_end)
            dest_end = balanced_end(text, end, '(', ')', limit)
            if dest_end:
                add(end, dest_end)
                # Nested brackets in visible text are prose, not separate refs.
                i = dest_end
                continue
        if text[end:end + 1] == '[':
            ref_end = close.get(end)
            if ref_end:
                reference = normalise_label(text[end + 1:ref_end - 1])
                if (reference or label) in definitions:
                    add(end, ref_end)
                    if not reference:
                        add(opening, end)
                    i = ref_end
                    continue
        if label in definitions:
            add(opening, end)
        i = end
    return spans


def normalise_label(label):
    return ' '.join(re.sub(r'\\([!"#$%&\'()*+,\-./:;<=>?@\[\]\\^_`{|}~])', r'\1', label).split()).casefold()


_QUOTES = {'"': '"', "'": "'", '\u201c': '\u201d', '\u2018': '\u2019'}
_QUOTE = re.compile('["\'\u201c\u2018]')
_EMPHASISED_QUOTE = re.compile('[*_]["\'\u201c\u2018]')
# Leading elisions and decades are apostrophes, not the start of a quotation.
_ELISION = re.compile(r"(?:\d{2}s|cause|em|tis|twas|til)\b", re.I)
# Categories that may sit before a delimiter run that opens emphasis: an
# opening bracket (Ps) or an opening quote (Pi). Whitespace and the start of
# the text are handled separately.
_OPENING_PUNCTUATION = ('Ps', 'Pi')


def _escaped(text, pos):
    """True if the character at pos is preceded by an odd run of backslashes."""
    start = pos
    while start and text[start - 1] == '\\':
        start -= 1
    return (pos - start) % 2 == 1


def _emphasis_flanked(text, start, end):
    """Whether delimiter runs at start and end flank their content as emphasis.

    Deliberately stricter than CommonMark, which also accepts a run preceded by
    any punctuation: a run glued to a path or a glob (``src/*``) must not open a
    quotation. Missing a protection is safer here than protecting prose that
    was never quoted.
    """
    if start:
        before = text[start - 1]
        if not (before.isspace() or unicodedata.category(before) in _OPENING_PUNCTUATION):
            return False
    if end < len(text):
        after = text[end]
        if not (after.isspace() or unicodedata.category(after).startswith('P')):
            return False
    return True


def _verbatim_regions(text):
    """Code blocks, blockquotes and inline code, as the Markdown strategy sees them.

    Built from the same primitives markdown_spans uses, so both agree on which
    regions are code; quotation marks inside them are never scanned.
    """
    from britfix_core import MarkdownStrategy

    markdown = MarkdownStrategy()
    n = len(text)
    regions = []
    backticks = {}
    pos = 0
    while pos < n:
        if pos == 0 or text[pos - 1] == '\n':
            end = _code_block_end(markdown, text, pos)
            if end is not None:
                regions.append((pos, end))
                pos = end
                continue
        match = _STRUCTURE.search(text, pos)
        if not match:
            break
        p = match.start()
        if text[p] != '`':
            pos = p + 1
            continue
        run = match.end() - p
        if run not in backticks:
            backticks[run] = _literal_finder(text, '`' * run)
        hit = backticks[run](p + run)
        if hit is None:
            # As in the strategy: step one backtick and retry shorter runs.
            pos = p + 1
        else:
            regions.append((p, hit[1]))
            pos = hit[1]
    return regions


def quotation_spans(text, all_quotes=False):
    """Emphasised quotations are verbatim; broader prose quoting is opt-in."""
    n = len(text)
    spans = []
    regions = _verbatim_regions(text)
    starts = [start for start, _ in regions]
    # One pass for paragraph ends, then a lookup per quotation: recomputing the
    # boundary from every quotation mark is quadratic on a long paragraph.
    boundaries = [max(m.start() - 1, 0) for m in _BOUNDARY.finditer(text)] + [n]

    def paragraph_end(pos):
        return boundaries[bisect.bisect_right(boundaries, pos)] if pos < n else n

    def region_at(pos):
        k = bisect.bisect_right(starts, pos) - 1
        return regions[k] if k >= 0 and pos < regions[k][1] else None

    # Only a quotation mark glued to an emphasis delimiter can open a protected
    # span by default, so the default scan skips every other quotation mark.
    candidate = _QUOTE if all_quotes else _EMPHASISED_QUOTE
    pos = 0
    while pos < n:
        match = candidate.search(text, pos)
        if not match:
            break
        i = match.end() - 1
        region = region_at(i)
        if region:
            pos = region[1]
            continue
        opening = text[i]
        if _escaped(text, i):
            pos = i + 1
            continue
        if opening in ("'", '\u2018'):
            # Apostrophes inside or straight after a word are not openers, and
            # nor are leading elisions and decades.
            if (i and text[i - 1].isalnum()) or _ELISION.match(text, i + 1):
                pos = i + 1
                continue
        delimiter = text[i - 1] if i and text[i - 1] in '*_' else None
        run_start = i
        if delimiter:
            while run_start and text[run_start - 1] == delimiter:
                run_start -= 1
        limit = paragraph_end(i)
        closing = _QUOTES[opening]
        # Step over whole code regions: a quotation mark inside code must not
        # close a quotation opened in prose, and a span must never cover part
        # of a code region.
        k = bisect.bisect_left(starts, i + 1)
        block = starts[k] if k < len(regions) else n
        j = i + 1
        while j < limit:
            if j >= block:
                j = regions[k][1]
                k += 1
                block = starts[k] if k < len(regions) else n
                continue
            if text[j] == '\\':
                j += 2
                continue
            if text[j] == closing:
                # An apostrophe within a word cannot close a quoted phrase.
                if closing in ("'", '\u2019') and j + 1 < n and text[j + 1].isalnum():
                    j += 1
                    continue
                break
            j += 1
        matched = j < limit
        emphasised = False
        run_end = j + 1
        if matched and delimiter:
            end = j + 1
            while end < n and text[end] == delimiter:
                end += 1
            # Equal runs either side, flanked as emphasis, or it is not one.
            if end - (j + 1) == i - run_start and _emphasis_flanked(text, run_start, end):
                emphasised = True
                run_end = end
        if matched and (all_quotes or emphasised):
            spans.append((run_start if emphasised else i, run_end))
            pos = run_end
        elif all_quotes and opening in ('"', '\u201c', '\u2018'):
            # Unclosed: preserve the rest of the paragraph, but never half of a
            # code region.
            end = limit
            region = region_at(end)
            if region:
                end = region[0]
            if end > i:
                spans.append((i, end))
            pos = max(end, i + 1)
        else:
            pos = i + 1
    return spans
