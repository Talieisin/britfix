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
#
# Everything here works line by line on the text between the quotes. A bare
# carriage return does not start a line, so in a file whose only line ending is
# one, only the first line of each docstring is examined.
_LINE = re.compile(r'(?m)^[^\r\n]*')

# The sections that document names. Prose under any other heading, Notes and
# Examples among them, is left to be corrected.
_SECTIONS = frozenset({'args', 'arguments', 'keyword args', 'keyword arguments',
                       'parameters', 'other parameters', 'attributes',
                       'returns', 'yields', 'raises', 'receives', 'warns'})
# Google ends a section heading with a colon; NumPy underlines it with dashes.
_GOOGLE_HEADING = re.compile(r'([ \t]*)([A-Za-z][A-Za-z ]*[A-Za-z])[ \t]*:[ \t]*')
_NUMPY_TITLE = re.compile(r'([ \t]*)([A-Za-z][A-Za-z ]*[A-Za-z])[ \t]*')
_NUMPY_UNDERLINE = re.compile(r'([ \t]*)-{3,}[ \t]*')

# Google style. The bare "name:" and "name : type" forms are recognised
# anywhere, as they always have been. The typed form is recognised only inside
# a section block, because "Deprecated (since the 2.0 release): ..." is a
# sentence rather than a label and must keep its corrections.
_GOOGLE_LABEL = re.compile(r'[ \t]*\*{0,2}(\w+)[ \t]*:')
_GOOGLE_TYPED_LABEL = re.compile(r'[ \t]*\*{0,2}(\w+)[ \t]*\([^()\r\n]*\)[ \t]*:')

# Sphinx info fields whose payload names a parameter, attribute or exception.
# The field name identifies these on its own, so they need no section.
# Longest first so ":parameter x:" is not read as ":param" followed by "eter x".
_SPHINX_FIELDS = ('param', 'parameter', 'arg', 'argument', 'key', 'keyword',
                  'kwarg', 'var', 'ivar', 'cvar',
                  'raises', 'raise', 'except', 'exception')
_SPHINX_FIELD = re.compile(
    r'[ \t]*:(?:' + '|'.join(sorted(_SPHINX_FIELDS, key=len, reverse=True))
    + r')[ \t]+([^:\r\n]+):')

# The three type fields are the one exception to protecting only the label: the
# payload after their closing colon is a type expression by definition, never
# prose, so ":type c: color" naming a class keeps that class name. Fields whose
# payload is prose, ":returns:" and ":raises ValueError:" among them, are not
# listed here and keep having their descriptions corrected.
_SPHINX_TYPE_FIELD = re.compile(
    r'[ \t]*:(?:vartype|rtype|type)(?=[ \t:])[ \t]*([^:\r\n]*):?[^\r\n]*')

# A NumPy name line is wholly names, optionally starred, optionally " : type".
# The format puts the description on a more deeply indented line beneath, and
# that is what separates a name line from a run of prose at the same indent.
_NUMPY_NAME = re.compile(
    r'([ \t]*)(\*{0,2}[A-Za-z_]\w*(?:[ \t]*,[ \t]*\*{0,2}[A-Za-z_]\w*)*)'
    r'(?:[ \t]*:[^\r\n]*)?[ \t]*')


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


def _indent_width(text):
    return len(text) - len(text.lstrip(' \t'))


def _section_name(match):
    return ' '.join(match.group(2).split()).lower()


def _google_section_lines(lines):
    """Indices of the lines inside the body of a Google parameter section.

    A section's body is what is indented under its heading, so the open
    headings behave as a stack and one pass over the lines is enough.
    """
    inside = set()
    open_indents = []
    for index, line in enumerate(lines):
        text = line.group()
        if not text.strip():
            continue
        width = _indent_width(text)
        while open_indents and width <= open_indents[-1]:
            open_indents.pop()
        if open_indents:
            inside.add(index)
        heading = _GOOGLE_HEADING.fullmatch(text)
        if heading and _section_name(heading) in _SECTIONS:
            open_indents.append(width)
    return inside


def _numpy_section_lines(lines):
    """Line index to section indent, for lines in a NumPy section body."""
    headings = []
    for index in range(len(lines) - 1):
        title = _NUMPY_TITLE.fullmatch(lines[index].group())
        underline = _NUMPY_UNDERLINE.fullmatch(lines[index + 1].group())
        if title and underline and title.group(1) == underline.group(1):
            headings.append((index, title.group(1), _section_name(title)))
    inside = {}
    for position, (index, indent, name) in enumerate(headings):
        if name not in _SECTIONS:
            continue
        # A section ends at the next underlined heading, whatever it is called,
        # so an underlined Notes closes this one and is itself left as prose.
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        for body in range(index + 2, end):
            inside[body] = indent
    return inside


def _parameter_labels(prose):
    """Every parameter label as (span, documented name).

    The span covers the label alone, never the description beside it. The name
    is empty where the form documents none, as ":rtype: bool" does, and where
    the label sits outside a section: a shape is not a record of an identifier,
    and only a name a section documents is worth protecting elsewhere.
    """
    lines = list(_LINE.finditer(prose))
    google = _google_section_lines(lines)
    numpy = _numpy_section_lines(lines)
    labels = []
    for index, line in enumerate(lines):
        text = line.group()
        base = line.start()
        sectioned = index in google
        match = _GOOGLE_LABEL.match(text)
        if match:
            labels.append(((base + match.start(), base + match.end()),
                           match.group(1)))
        elif sectioned:
            match = _GOOGLE_TYPED_LABEL.match(text)
            if match:
                labels.append(((base + match.start(), base + match.end()), match.group(1)))
        match = _SPHINX_FIELD.match(text)
        if match:
            # ":param str color:" carries the type first, so the name is last.
            payload = match.group(1).split()
            labels.append(((base + match.start(), base + match.end()),
                           payload[-1].lstrip('*') if payload else ''))
        match = _SPHINX_TYPE_FIELD.match(text)
        if match:
            labels.append(((base + match.start(), base + match.end()),
                           match.group(1).strip().lstrip('*')))
        indent = numpy.get(index)
        if indent is None:
            continue
        match = _NUMPY_NAME.fullmatch(text)
        if not match or match.group(1) != indent:
            continue
        following = lines[index + 1].group() if index + 1 < len(lines) else ''
        if not following.strip() or _indent_width(following) <= len(indent):
            continue  # No description beneath it, so the line is prose.
        # One line may document several names against one description.
        for name in match.group(2).split(','):
            labels.append(((base, base + len(text)), name.strip().lstrip('*')))
    return labels


def _parameter_label_spans(prose):
    """Spans of Google, Sphinx and NumPy parameter labels, descriptions excluded."""
    return [span for span, _ in _parameter_labels(prose)]


def _parameter_label_names(prose):
    """Identifier names that a docstring documents as parameters."""
    return {name for _, name in _parameter_labels(prose) if name.isidentifier()}


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
        # A name a docstring documents as a parameter names code just as a name
        # the file defines does, so it protects its prose mentions file-wide
        # rather than only inside the docstring that documents it.
        for doc in docs:
            names.update(_parameter_label_names(doc.value))

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
