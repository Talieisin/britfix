"""Verbatim spans used by spelling strategies; no document reserialisation."""

import re
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
    marker = uuid.uuid4().hex
    while marker in text:
        marker = uuid.uuid4().hex
    originals = []
    pieces = []
    pos = 0
    for start, end in merge_spans(spans):
        token = f'\x00{marker}:{len(originals)}\x00'
        original = text[start:end]
        replacement = token + ''.join(re.findall(r'\r\n|\r|\n', original))
        originals.append((replacement, original))
        pieces.extend((text[pos:start], replacement))
        pos = end
    pieces.append(text[pos:])

    def restore(result):
        for replacement, original in originals:
            result = result.replace(replacement, original)
        return result

    return ''.join(pieces), restore


def balanced_end(text, start, opening='[', closing=']'):
    depth = 0
    i = start
    quote = None
    while i < len(text):
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


def markdown_spans(text):
    spans = url_spans(text)
    # Tags may contain quoted > characters. Script/style bodies and HTML
    # comments are wholly machine-readable, including unclosed blocks.
    for pattern in [
        r'<!--[\s\S]*?(?:-->|\Z)',
        r'<(script|style)\b[^>]*>[\s\S]*?(?:</\1\s*>|\Z)',
        r'</?[A-Za-z](?:[^<>"\']|"[^"]*"|\'[^\']*\')*>',
    ]:
        spans.extend(m.span() for m in re.finditer(pattern, text, re.I))

    definitions = set()
    definition_spans = []
    for match in re.finditer(r'(?m)^ {0,3}\[', text):
        start = match.end() - 1
        end = balanced_end(text, start)
        if end is None or text[end:end + 1] != ':':
            continue
        label = normalise_label(text[start + 1:end - 1])
        definitions.add(label)
        line_end = text.find('\n', end)
        if line_end == -1:
            line_end = len(text)
        # Include indented continuation lines (destination/title on next line).
        while line_end < len(text):
            next_end = text.find('\n', line_end + 1)
            next_end = len(text) if next_end == -1 else next_end
            if not re.match(r'[ \t]+\S', text[line_end + 1:next_end]):
                break
            line_end = next_end
        definition_spans.append((match.start(), line_end))
    spans.extend(definition_spans)

    i = 0
    while i < len(text):
        if text[i] == '\\':
            i += 2
            continue
        if text[i] != '[':
            i += 1
            continue
        end = balanced_end(text, i)
        if end is None:
            i += 1
            continue
        label = normalise_label(text[i + 1:end - 1])
        if text[end:end + 1] == '(':
            dest_end = balanced_end(text, end, '(', ')')
            if dest_end:
                spans.append((end, dest_end))
                # Nested brackets in visible text are prose, not separate refs.
                i = dest_end
                continue
        if text[end:end + 1] == '[':
            ref_end = balanced_end(text, end)
            if ref_end:
                reference = normalise_label(text[end + 1:ref_end - 1])
                if (reference or label) in definitions:
                    spans.append((end, ref_end))
                    if not reference:
                        spans.append((i, end))
                    i = ref_end
                    continue
        if label in definitions:
            spans.append((i, end))
        i = end
    return spans


def normalise_label(label):
    return ' '.join(re.sub(r'\\([!"#$%&\'()*+,\-./:;<=>?@\[\]\\^_`{|}~])', r'\1', label).split()).casefold()


def quotation_spans(text, all_quotes=False):
    """Explicit italic quotations are verbatim; broader prose quoting is opt-in."""
    spans = []
    pairs = {'"': '"', "'": "'", '\u201c': '\u201d', '\u2018': '\u2019'}
    i = 0
    while i < len(text):
        opening = text[i]
        if opening == '\\':
            i += 2
            continue
        if opening not in pairs:
            i += 1
            continue
        # Apostrophes inside words or immediately after a word are not openers.
        if opening in ("'", '\u2018') and i and text[i - 1].isalnum():
            i += 1
            continue
        if opening == "'" and re.match(r"(?:\d{2}s|cause|em|tis|twas|til)\b", text[i + 1:], re.I):
            i += 1
            continue
        italic = i > 0 and text[i - 1] in '*_'
        paragraph = re.search(r'\r?\n[ \t]*\r?\n', text[i:])
        limit = i + paragraph.start() if paragraph else len(text)
        closing = pairs[opening]
        j = i + 1
        while j < limit:
            if text[j] == '\\':
                j += 2
                continue
            if text[j] == closing:
                # An apostrophe within a word cannot close a quoted phrase.
                if closing in ("'", '\u2019') and j + 1 < len(text) and text[j + 1].isalnum():
                    j += 1
                    continue
                break
            j += 1
        matched = j < limit
        italic = italic and matched and text[j + 1:j + 2] == text[i - 1]
        if matched and (all_quotes or italic):
            spans.append((i - 1 if italic else i, j + 2 if italic else j + 1))
            i = j + 1
        elif all_quotes and opening in ('"', '\u201c', '\u2018'):
            spans.append((i, limit))
            i = limit
        else:
            i += 1
    return spans
