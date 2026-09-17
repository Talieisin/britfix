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


class ProcessingSkipped(Exception):
    """Input was not safe to process; distinguish this from a clean scan."""


def _row_starts(content, pattern):
    """Return the start offset of every row, plus len(content) as a sentinel."""
    starts = [match.start() for match in pattern.finditer(content)]
    starts.append(len(content))
    return starts


def _inconsistent(detail):
    return ProcessingSkipped(f'Python offsets inconsistent: {detail}')


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
                    regions.append((start, end))
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
                match = re.match(r'(?i)(?:r|u)?("""|\'\'\'|"|\')', raw)
                if not match:
                    continue
                delimiter = match.group(1)
                regions.append((start + match.end(), end - len(delimiter)))
        except (IndexError, UnicodeDecodeError) as exc:
            raise _inconsistent(str(exc)) from exc

        replacements = []
        for start, end in regions:
            prose = content[start:end]
            protected = quotation_spans(prose, True) + url_spans(prose)
            protected += [m.span() for m in re.finditer(r'`+[^`]*`+|\b\w+(?:\.\w+)+\b|\\(?:\r?\n|.)', prose)]
            # Parameter labels: Google/NumPy and Sphinx forms.
            protected += [m.span() for m in re.finditer(
                r'(?m)^[ \t]*(?:\*{0,2}\w+[ \t]*:|:param[ \t]+[^:\r\n]+:)', prose)]
            protected = merge_spans(protected)
            for a, b, old, new in corrector.find_replacements(prose):
                if old in names or any(x < b and a < y for x, y in protected):
                    continue
                replacements.append((start + a, start + b, old, new))
        for start, end, old, _ in replacements:
            if content[start:end] != old:
                raise _inconsistent(f'replacement at offset {start}')
        return sorted(replacements)

    def process(self, content, corrector):
        replacements = self.find_safe_replacements(content, corrector)
        counts = {}
        result = content
        for start, end, old, new in reversed(replacements):
            result = result[:start] + new + result[end:]
            counts[old.lower()] = counts.get(old.lower(), 0) + 1
        return result, counts
