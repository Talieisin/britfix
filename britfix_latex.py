"""Bounded LaTeX lexical protection; does not expand macros or catcodes."""

import re

from britfix_spans import merge_spans, quotation_spans, url_spans


PROSE_COMMANDS = {
    'textbf', 'textit', 'textrm', 'textsf', 'emph', 'part', 'chapter',
    'section', 'subsection', 'subsubsection', 'paragraph', 'subparagraph',
    'title', 'caption', 'footnote',
}
PROTECTED_ENVIRONMENTS = {
    'math', 'displaymath', 'equation', 'align', 'alignat', 'gather',
    'multline', 'eqnarray', 'verbatim', 'Verbatim', 'lstlisting', 'minted',
}


def group_end(text, start, limit):
    opening = text[start]
    closing = {'{': '}', '[': ']'}[opening]
    depth = 1
    i = start + 1
    while i < limit:
        if text[i] == '\\':
            i += 2
            continue
        if text[i] == '%':
            newline = text.find('\n', i, limit)
            i = limit if newline == -1 else newline + 1
            continue
        if opening == '[' and text[i] == '{':
            end = group_end(text, i, limit)
            if end is None:
                return None
            i = end
            continue
        if text[i] == opening:
            depth += 1
        elif text[i] == closing:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def find_delimiter(text, delimiter, start, limit):
    i = start
    while i < limit:
        if text.startswith(delimiter, i):
            return i
        if text[i] == '\\':
            i += 2
        elif text[i] == '%':
            newline = text.find('\n', i, limit)
            i = limit if newline == -1 else newline + 1
        else:
            i += 1
    return None


def latex_spans(text):
    spans = url_spans(text) + quotation_spans(text, True)
    notes = []

    def unfinished(start, reason):
        spans.append((start, len(text)))
        notes.append(reason)

    def scan(start, limit):
        i = start
        while i < limit:
            if text[i] == '%':
                # Comment prose remains eligible, but cannot introduce TeX
                # structure affecting the following source lines.
                newline = text.find('\n', i, limit)
                i = limit if newline == -1 else newline + 1
                continue
            if text[i] == '$' or text.startswith(('\\(', '\\['), i):
                if text.startswith('$$', i):
                    opening = closing = '$$'
                elif text[i] == '$':
                    opening = closing = '$'
                else:
                    opening = text[i:i + 2]
                    closing = '\\)' if opening == '\\(' else '\\]'
                end = find_delimiter(text, closing, i + len(opening), limit)
                if end is None:
                    unfinished(i, 'unterminated LaTeX mathematics')
                    return
                end += len(closing)
                spans.append((i, end))
                i = end
                continue
            if text[i] != '\\':
                i += 1
                continue
            command = re.match(r'\\([A-Za-z@]+\*?|.)', text[i:limit], re.S)
            if not command:
                spans.append((i, limit))
                return
            name = command.group(1).rstrip('*')
            command_end = i + command.end()
            spans.append((i, command_end))
            if len(command.group(1)) == 1 and not command.group(1).isalpha():
                i = command_end
                continue

            if name in {'verb', 'lstinline', 'mintinline'}:
                pos = command_end
                while pos < limit and text[pos].isspace():
                    pos += 1
                if pos < limit and text[pos] == '[':
                    pos = group_end(text, pos, limit)
                    if pos is None:
                        unfinished(i, 'unterminated inline verbatim options')
                        return
                if name == 'mintinline':
                    while pos < limit and text[pos].isspace():
                        pos += 1
                    if pos >= limit or text[pos] != '{':
                        unfinished(i, 'unsupported inline minted language syntax')
                        return
                    pos = group_end(text, pos, limit)
                    if pos is None:
                        unfinished(i, 'unterminated inline minted language')
                        return
                while pos < limit and text[pos].isspace():
                    pos += 1
                if pos >= limit:
                    unfinished(i, 'unterminated inline verbatim')
                    return
                if text[pos] == '{' and name != 'verb':
                    end = group_end(text, pos, limit)
                else:
                    closing = text.find(text[pos], pos + 1, limit)
                    end = None if closing == -1 else closing + 1
                if end is None:
                    unfinished(i, 'unterminated inline verbatim')
                    return
                spans.append((i, end))
                i = end
                continue

            pos = command_end
            mandatory = 0
            while pos < limit:
                gap = pos
                while gap < limit and text[gap].isspace():
                    gap += 1
                if gap >= limit or text[gap] not in '[{':
                    break
                end = group_end(text, gap, limit)
                if end is None:
                    unfinished(i, 'unterminated LaTeX command argument')
                    return
                if text[gap] == '[':
                    spans.append((gap, end))
                else:
                    mandatory += 1
                    if name == 'begin' and mandatory == 1:
                        env = text[gap + 1:end - 1]
                        if env.rstrip('*') in PROTECTED_ENVIRONMENTS:
                            terminator = '\\end{' + env + '}'
                            close = text.find(terminator, end, limit)
                            if close == -1:
                                unfinished(i, f'unterminated LaTeX environment {env}')
                                return
                            close += len(terminator)
                            spans.append((i, close))
                            pos = close
                            break
                    if name in PROSE_COMMANDS or (name == 'href' and mandatory == 2):
                        spans.extend([(gap, gap + 1), (end - 1, end)])
                        scan(gap + 1, end - 1)
                    else:
                        spans.append((gap, end))
                pos = end
            i = pos

    scan(0, len(text))
    return merge_spans(spans), notes


def latex_replacements(text, corrector):
    spans, notes = latex_spans(text)
    candidates = [r for r in corrector.find_replacements(text)
                  if not any(a < r[1] and r[0] < b for a, b in spans)]
    return candidates, notes
