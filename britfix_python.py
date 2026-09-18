"""Python prose correction using lexical positions and real docstring nodes."""

import ast
import bisect
import io
import re
import tokenize

from britfix_spans import merge_spans, quotation_spans, url_spans

IDENTIFIER_PROTECTION_MODES = ('defined', 'all')

# Rows exactly as each parser counts them. tokenize, fed by StringIO.readline,
# ends a row only at LF. The CPython parser behind ast also ends one at a lone
# CR. str.splitlines() matches neither: it also splits on FF, VT, NEL, U+2028
# and similar, which would shift every later offset.
TOKEN_ROWS = re.compile(r'[^\n]*\n|[^\n]+')
AST_ROWS = re.compile(r'[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+')

_DOC_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
_NAMED_DEFINITIONS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef,
                      ast.ExceptHandler, ast.MatchAs, ast.MatchStar,
                      ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple)

# Docstring parameter labels name code, so they are syntax rather than prose.
# Only the label is protected: the description beside it stays prose and is
# still corrected, or whole documented sections would stop being corrected.

# Google style, with the optional parenthesised type the style guide uses:
# "name:", "name : type", "name (bool):", "name (int, optional):", "**kw (dict):".
# A word followed by a space rather than a colon cannot start a label, so an
# ordinary sentence that happens to end in a colon stays prose.
_GOOGLE_LABEL = re.compile(r'(?m)^[ \t]*\*{0,2}\w+(?:[ \t]*\([^()\r\n]*\))?[ \t]*:')

# Sphinx info fields whose payload names a parameter, attribute or exception.
# Longest first so ":parameter x:" is not read as ":param" followed by "eter x".
_SPHINX_FIELDS = ('param', 'parameter', 'arg', 'argument', 'key', 'keyword',
                  'kwarg', 'var', 'ivar', 'cvar',
                  'raises', 'raise', 'except', 'exception')
_SPHINX_FIELD = re.compile(
    r'(?m)^[ \t]*:(?:' + '|'.join(sorted(_SPHINX_FIELDS, key=len, reverse=True))
    + r')[ \t]+[^:\r\n]+:')

# The three type fields are the one exception to protecting only the label: the
# payload after their closing colon is a type expression by definition, never
# prose, so ":type c: color" naming a class keeps that class name. Fields whose
# payload is prose, ":returns:" and ":raises ValueError:" among them, are not
# listed here and keep having their descriptions corrected.
_SPHINX_TYPE_FIELD = re.compile(r'(?m)^[ \t]*:(?:vartype|rtype|type)(?=[ \t:])[^\r\n]*')

# NumPy style, found from the dashed underline rather than guessed at from
# indentation. The backreference holds the underline to the heading's own
# indent. As for every label form here, a lone CR is not a line start to (?m),
# so a file whose only line ending is one is not scanned for labels.
_NUMPY_HEADING = re.compile(
    r'(?m)^([ \t]*)([A-Za-z][A-Za-z ]*[A-Za-z])[ \t]*\r?\n\1-{3,}[ \t]*(?=\r?\n|\Z)')
_NUMPY_SECTIONS = frozenset({'parameters', 'other parameters', 'attributes',
                             'returns', 'yields', 'raises', 'receives', 'warns'})
# A name line is wholly names, optionally starred, optionally " : type". Any
# other text at that indent is prose and keeps its corrections.
_NUMPY_NAME = re.compile(
    r'([ \t]*)\*{0,2}[A-Za-z_]\w*(?:[ \t]*,[ \t]*\*{0,2}[A-Za-z_]\w*)*'
    r'(?:[ \t]*:[^\r\n]*)?[ \t]*')
_LINE = re.compile(r'(?m)^[^\r\n]*')


class ProcessingSkipped(Exception):
    """Input was not safe to process; distinguish this from a clean scan."""


def _row_starts(content, pattern):
    """Return the start offset of every row, plus len(content) as a sentinel."""
    starts = [match.start() for match in pattern.finditer(content)]
    starts.append(len(content))
    return starts


def _apply(content, replacements):
    """Apply sorted, non-overlapping (start, end, old, new) replacements."""
    parts = []
    position = 0
    for start, end, _, new in replacements:
        parts.append(content[position:start])
        parts.append(new)
        position = end
    parts.append(content[position:])
    return ''.join(parts)


def _inconsistent(detail):
    return ProcessingSkipped(f'Python offsets inconsistent: {detail}')


def _numpy_label_spans(prose):
    """Spans of the name lines of every recognised NumPy section."""
    headings = list(_NUMPY_HEADING.finditer(prose))
    sections = []
    for index, heading in enumerate(headings):
        if ' '.join(heading.group(2).split()).lower() not in _NUMPY_SECTIONS:
            continue
        # A section ends at the next underlined heading of any name, so an
        # unlisted one such as Notes both closes this section and is skipped.
        end = headings[index + 1].start() if index + 1 < len(headings) else len(prose)
        sections.append((heading.end(), end, heading.group(1)))
    if not sections:
        return []
    spans = []
    current = 0
    # Lines are visited once in order, so many sections cost no rescan.
    for line in _LINE.finditer(prose):
        while current < len(sections) and sections[current][1] <= line.start():
            current += 1
        if current == len(sections) or line.start() <= sections[current][0]:
            continue
        match = _NUMPY_NAME.fullmatch(line.group())
        if match and match.group(1) == sections[current][2]:
            spans.append(line.span())
    return spans


def _parameter_label_spans(prose):
    """Spans of Google, Sphinx and NumPy parameter labels, descriptions excluded."""
    spans = [match.span() for match in _GOOGLE_LABEL.finditer(prose)]
    spans += [match.span() for match in _SPHINX_FIELD.finditer(prose)]
    spans += [match.span() for match in _SPHINX_TYPE_FIELD.finditer(prose)]
    spans += _numpy_label_spans(prose)
    return spans


class PythonStrategy:
    supports_interactive = True

    def __init__(self, identifier_protection=None):
        if identifier_protection is not None and identifier_protection not in IDENTIFIER_PROTECTION_MODES:
            raise ValueError(f'identifier_protection must be one of {IDENTIFIER_PROTECTION_MODES}')
        self.identifier_protection = identifier_protection

    def _mode(self):
        if self.identifier_protection is not None:
            return self.identifier_protection
        from britfix_core import _CONFIG  # Deferred: britfix_core imports this module.
        return _CONFIG['strategies'].get('code', {}).get('python_identifier_protection', 'defined')

    def find_safe_replacements(self, content, corrector):
        mode = self._mode()
        try:
            tree = ast.parse(content)
            tokens = list(tokenize.generate_tokens(io.StringIO(content).readline))
        except (SyntaxError, ValueError, tokenize.TokenError) as exc:
            raise ProcessingSkipped(f'Python syntax/tokenisation: {exc}') from exc

        token_rows = _row_starts(content, TOKEN_ROWS)
        ast_rows = _row_starts(content, AST_ROWS)

        def token_offset(position):
            row, col = position
            return token_rows[row - 1] + col

        def ast_offset(row, byte_col):
            line = content[ast_rows[row - 1]:ast_rows[row]]
            return ast_rows[row - 1] + len(line.encode('utf-8')[:byte_col].decode('utf-8'))

        docs = []
        constants = []
        defined = set()
        for node in ast.walk(tree):
            if isinstance(node, _DOC_OWNERS) and node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    docs.append(value)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                constants.append(node)
            if mode != 'defined':
                continue
            if isinstance(node, _NAMED_DEFINITIONS):
                if node.name:
                    defined.add(node.name)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                defined.add(node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
                defined.add(node.attr)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                defined.update(node.names)
            elif isinstance(node, ast.MatchMapping) and node.rest:
                defined.add(node.rest)
            elif isinstance(node, ast.alias):
                if node.asname:
                    defined.add(node.asname)
                elif node.name != '*':
                    defined.add(node.name.split('.')[0])

        doc_ids = {id(node) for node in docs}
        if mode == 'all':
            names = {token.string for token in tokens if token.type == tokenize.NAME}
        else:
            names = defined
        names.update(node.value for node in constants
                     if id(node) not in doc_ids and node.value.isidentifier())

        regions = []
        try:
            for token in tokens:
                if token.type == tokenize.COMMENT:
                    start, end = token_offset(token.start), token_offset(token.end)
                    if content[start:end] != token.string:
                        raise _inconsistent(f'comment at row {token.start[0]}')
                    if start == 0 and token.string.startswith('#!'):
                        continue
                    regions.append((start, end, False))
            string_starts = sorted(token_offset(t.start) for t in tokens if t.type == tokenize.STRING)
            for doc in docs:
                start = ast_offset(doc.lineno, doc.col_offset)
                end = ast_offset(doc.end_lineno, doc.end_col_offset)
                inside = bisect.bisect_left(string_starts, end) - bisect.bisect_left(string_starts, start)
                if inside != 1:
                    continue  # Implicit concatenation: preserve rather than rebuild.
                raw = content[start:end]
                try:
                    literal = ast.literal_eval(raw)
                except Exception as exc:
                    raise _inconsistent(f'docstring at row {doc.lineno}') from exc
                if literal != doc.value:
                    raise _inconsistent(f'docstring at row {doc.lineno}')
                match = re.match(r'(?i)(r|u)?("""|\'\'\'|"|\')', raw)
                if not match:
                    continue
                delimiter = match.group(2)
                escapes = (match.group(1) or '').lower() != 'r'
                regions.append((start + match.end(), end - len(delimiter), escapes))
        except (IndexError, UnicodeDecodeError) as exc:
            raise _inconsistent(str(exc)) from exc

        replacements = []
        for start, end, escapes in regions:
            prose = content[start:end]
            protected = quotation_spans(prose, True) + url_spans(prose)
            protected += [m.span() for m in re.finditer(r'`+[^`]*`+|\b\w+(?:\.\w+)+\b|\\(?:\r?\n|.)', prose)]
            if escapes:
                # A named escape such as \N{...} is part of the string's value, not prose.
                protected += [m.span() for m in re.finditer(r'\\N\{[^}]*\}', prose)]
            protected += _parameter_label_spans(prose)
            protected = merge_spans(protected)
            for a, b, old, new in corrector.find_replacements(prose):
                if old in names or any(x < b and a < y for x, y in protected):
                    continue
                replacements.append((start + a, start + b, old, new))
        for start, end, old, _ in replacements:
            if content[start:end] != old:
                raise _inconsistent(f'replacement at offset {start}')
        replacements.sort()
        if replacements:
            # Safety net: the source parsed, so the corrected source must parse too.
            try:
                ast.parse(_apply(content, replacements))
            except (SyntaxError, ValueError) as exc:
                raise ProcessingSkipped(f'Python correction would break parsing: {exc}') from exc
        return replacements

    def process(self, content, corrector):
        replacements = self.find_safe_replacements(content, corrector)
        counts = {}
        for _, _, old, _ in replacements:
            counts[old.lower()] = counts.get(old.lower(), 0) + 1
        return _apply(content, replacements), counts
