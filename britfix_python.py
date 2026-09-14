"""Python prose correction using lexical positions and real docstring nodes."""

import ast
import io
import re
import tokenize

from britfix_spans import merge_spans, quotation_spans, url_spans


class ProcessingSkipped(Exception):
    """Input was not safe to process; distinguish this from a clean scan."""


class PythonStrategy:
    supports_interactive = True

    def find_safe_replacements(self, content, corrector):
        try:
            tree = ast.parse(content)
            tokens = list(tokenize.generate_tokens(io.StringIO(content).readline))
        except (SyntaxError, ValueError, tokenize.TokenError, IndentationError) as exc:
            raise ProcessingSkipped(f'Python syntax/tokenisation: {exc}') from exc

        lines = content.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))

        def token_offset(position):
            row, col = position
            return offsets[row - 1] + col

        def ast_offset(row, byte_col):
            return offsets[row - 1] + len(lines[row - 1].encode('utf-8')[:byte_col].decode('utf-8'))

        docs = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.body and isinstance(node.body[0], ast.Expr):
                    value = node.body[0].value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        docs.append(value)
        doc_ids = {id(node) for node in docs}
        names = {token.string for token in tokens if token.type == tokenize.NAME}
        names.update(node.value for node in ast.walk(tree)
                     if isinstance(node, ast.Constant) and isinstance(node.value, str)
                     and id(node) not in doc_ids and node.value.isidentifier())

        regions = []
        for token in tokens:
            if token.type == tokenize.COMMENT:
                start, end = token_offset(token.start), token_offset(token.end)
                if start == 0 and token.string.startswith('#!'):
                    continue
                regions.append((start, end))
        for doc in docs:
            start = ast_offset(doc.lineno, doc.col_offset)
            end = ast_offset(doc.end_lineno, doc.end_col_offset)
            strings = [t for t in tokens if t.type == tokenize.STRING
                       and start <= token_offset(t.start) < end]
            if len(strings) != 1:
                continue  # Implicit concatenation: preserve rather than rebuild.
            raw = content[start:end]
            match = re.match(r'(?i)(?:r|u)?("""|\'\'\'|"|\')', raw)
            if not match:
                continue
            delimiter = match.group(1)
            regions.append((start + match.end(), end - len(delimiter)))

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
        return sorted(replacements)

    def process(self, content, corrector):
        replacements = self.find_safe_replacements(content, corrector)
        counts = {}
        result = content
        for start, end, old, new in reversed(replacements):
            result = result[:start] + new + result[end:]
            counts[old.lower()] = counts.get(old.lower(), 0) + 1
        return result, counts
