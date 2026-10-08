"""Version 2 lexer, recursive-descent statement parser, and AST-backed expressions.

Indentation is never consulted. Python's expression grammar remains the semantic
base; token-aware surface translations add Kotlin conditionals and interpolation.
"""
from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from dataclasses import dataclass

HEADER = '#!pyfold 2'


class SyntaxErrorV2(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    start: int
    end: int
    line: int


def string_end(source, start):
    match = re.match(r"(?i:[rubf]{0,2})(\"\"\"|'''|\"|')", source[start:])
    if not match:
        return None
    quote = match[1]
    pos = start + len(match[0])
    while pos < len(source):
        if source[pos] == '\\':
            pos += 2
        elif source.startswith(quote, pos):
            return pos + len(quote)
        elif source.startswith('${', pos) and match[0] == '"':
            # Interpolations may contain nested calls, dicts and quoted strings.
            pos = interpolation_end(source, pos + 2) + 1
        else:
            pos += 1
    raise SyntaxErrorV2('Unterminated string')


def interpolation_end(source, start):
    depth, pos = 1, start
    while pos < len(source):
        if source[pos] in "\"'":
            pos = string_end(source, pos)
        elif source[pos] == '{':
            depth += 1
            pos += 1
        elif source[pos] == '}':
            depth -= 1
            if depth == 0:
                return pos
            pos += 1
        else:
            pos += 1
    raise SyntaxErrorV2('Unterminated ${...} interpolation')


def lex(source):
    tokens, pos, line = [], 0, 1
    while pos < len(source):
        start, start_line = pos, line
        ch = source[pos]
        if ch in ' \t\r':
            pos += 1
            continue
        if ch == '\n':
            kind, pos = 'newline', pos + 1
        elif ch == '#':
            end = source.find('\n', pos)
            pos = len(source) if end < 0 else end
            continue
        elif source.startswith('/*', pos):
            end = source.find('*/', pos + 2)
            if end < 0:
                raise SyntaxErrorV2(f'Unclosed comment at line {line}')
            pos = end + 2
            line += source[start:pos].count('\n')
            continue
        elif ch == '`':
            match = re.match(r'(`{3,})python\r?\n', source[pos:])
            if not match:
                raise SyntaxErrorV2(f'Expected fenced Python at line {line}')
            fence = match[1]
            end = re.search(r'(?m)^' + re.escape(fence) + r'[ \t]*\r?$', source[pos + len(match[0]):])
            if not end:
                raise SyntaxErrorV2(f'Unclosed Python block at line {line}')
            pos += len(match[0]) + end.end()
            kind = 'raw'
        elif (end := string_end(source, pos)) is not None:
            kind, pos = 'string', end
        elif ch.isalpha() or ch == '_':
            pos += 1
            while pos < len(source) and (source[pos].isalnum() or source[pos] == '_'):
                pos += 1
            kind = 'name'
        elif ch.isdigit() or (ch == '.' and pos + 1 < len(source) and source[pos+1].isdigit()):
            match = re.match(r'(?:0[xX][\da-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|(?:\d[\d_]*(?:\.[\d_]*)?|\.[\d_]+)(?:[eE][+-]?[\d_]+)?[jJ]?)', source[pos:])
            pos += len(match[0])
            kind = 'number'
        else:
            match = re.match(r'(?:\*\*=|//=|<<=|>>=|=>|->|&&|\|\||==|!=|<=|>=|\*\*|//|<<|>>|:=|\+=|-=|\*=|/=|%=|&=|\|=|\^=|\.\.\.|[{}()\[\],:;.+*/%<>=!~&|^@-])', source[pos:])
            if not match:
                raise SyntaxErrorV2(f'Unexpected {ch!r} at line {line}')
            pos += len(match[0])
            kind = 'op'
        text = source[start:pos]
        tokens.append(Token(kind, text, start, pos, start_line))
        line += text.count('\n')
    tokens.append(Token('eof', '', len(source), len(source), line))
    return tokens


def matching(tokens, start):
    pairs, stack = {'(': ')', '[': ']', '{': '}'}, []
    for i in range(start, len(tokens)):
        text = tokens[i].text
        if tokens[i].kind == 'string':
            continue
        if text in pairs:
            stack.append(pairs[text])
        elif text in (')', ']', '}'):
            if not stack or stack.pop() != text:
                raise SyntaxErrorV2('Mismatched expression delimiter')
            if not stack:
                return i
    raise SyntaxErrorV2('Unclosed expression delimiter')


def string_python(text):
    # Only unprefixed double-quoted strings interpolate. Single quotes are literal.
    if not text.startswith('"') or text.startswith('"""') or '${' not in text:
        return text
    inner, values, pos, start = text[1:-1], [], 0, 0
    while pos < len(inner):
        if inner[pos] == '\\':
            pos += 2
        elif inner.startswith('${', pos):
            literal = inner[start:pos]
            if literal:
                values.append(ast.Constant(ast.literal_eval('"' + literal + '"')))
            end = interpolation_end(inner, pos + 2)
            expression = expr(lex(inner[pos+2:end])[:-1])
            values.append(ast.FormattedValue(ast.parse(expression, mode='eval').body, -1, None))
            pos = start = end + 1
        else:
            pos += 1
    if start == 0:
        return text
    if start < len(inner):
        values.append(ast.Constant(ast.literal_eval('"' + inner[start:] + '"')))
    return ast.unparse(ast.JoinedStr(values))


def expr(tokens):
    tokens = [t for t in tokens if t.kind not in ('newline', 'eof')]
    if not tokens:
        return ''
    # Split top-level commas so conditionals can be arguments or tuple elements.
    pieces, start, i = [], 0, 0
    while i < len(tokens):
        if tokens[i].text in ('(', '[', '{') and tokens[i].kind == 'op':
            i = matching(tokens, i) + 1
        elif tokens[i].text == ',':
            pieces.append(tokens[start:i])
            start = i = i + 1
        else:
            i += 1
    if pieces:
        return ', '.join(expr(p) for p in pieces + [tokens[start:]])
    if tokens[0].text == 'if' and len(tokens) > 1 and tokens[1].text == '(':
        end = matching(tokens, 1)
        depth, i = 0, end + 1
        while i < len(tokens):
            if tokens[i].text in ('(', '[', '{') and tokens[i].kind == 'op':
                i = matching(tokens, i) + 1
                continue
            if tokens[i].text == 'if':
                depth += 1
            elif tokens[i].text == 'else':
                if depth == 0:
                    return f'({expr(tokens[end+1:i])} if {expr(tokens[2:end])} else {expr(tokens[i+1:])})'
                depth -= 1
            i += 1
        raise SyntaxErrorV2('Conditional expression requires else')
    result, i, saw_for = [], 0, False
    aliases = {'true':'True', 'false':'False', 'null':'None', '&&':'and', '||':'or', '!':'not'}
    while i < len(tokens):
        token = tokens[i]
        if token.kind == 'string':
            result.append(string_python(token.text))
        elif token.text == 'for' and i + 1 < len(tokens) and tokens[i+1].text == '(':
            end = matching(tokens, i + 1)
            result.append('for ' + expr(tokens[i+2:end]))
            saw_for = True
            i = end
        elif token.text in ('(', '[', '{'):
            end = matching(tokens, i)
            result.append(token.text + expr(tokens[i+1:end]) + tokens[end].text)
            i = end
        elif token.text == 'if' and not saw_for and i + 1 < len(tokens) and tokens[i+1].text == '(':
            result.append(expr(tokens[i:]))
            break
        else:
            # Attribute spellings are literal; only bare values map to constants.
            result.append(aliases.get(token.text, token.text) if i == 0 or tokens[i-1].text != '.' else token.text)
            saw_for = saw_for or token.text == 'for'
        i += 1
    return ' '.join(result)


class Parser:
    def __init__(self, source):
        self.source, self.tokens, self.i = source, lex(source), 0
        self.val_scopes = [set()]

    def peek(self, text=None):
        token = self.tokens[self.i]
        return token.text == text if text is not None else token

    def take(self, text=None):
        token = self.peek()
        if text is not None and token.text != text:
            raise SyntaxErrorV2(f'Expected {text!r} at line {token.line}, got {token.text!r}')
        self.i += 1
        return token

    def separators(self):
        while self.peek().kind == 'newline' or self.peek(';'):
            self.i += 1

    def collect(self, stops=(), newline=True):
        result = []
        while self.peek().kind != 'eof':
            t = self.peek()
            if (newline and t.kind == 'newline') or t.text in stops:
                break
            if t.text in ('(', '[', '{'):
                end = matching(self.tokens, self.i)
                result.extend(self.tokens[self.i:end+1])
                self.i = end + 1
            else:
                result.append(self.take())
        return result

    def group(self):
        self.take('(')
        tokens = self.collect(stops=(')',), newline=False)
        self.take(')')
        return expr(tokens)

    def suite(self):
        self.separators()
        self.take('{')
        lines = []
        self.separators()
        while not self.peek('}'):
            if self.peek().kind == 'eof':
                raise SyntaxErrorV2('Unclosed block')
            lines.append(self.statement())
            self.separators()
        self.take('}')
        return '\n'.join('    ' + line for line in ('\n'.join(lines) or 'pass').splitlines())

    def follow(self, keyword):
        old = self.i
        self.separators()
        if self.peek(keyword):
            self.take()
            return True
        self.i = old
        return False

    def statement(self):
        t = self.peek()
        if t.kind == 'raw':
            self.take()
            return '\n'.join(t.text.splitlines()[1:-1])
        if self.peek('async') and self.tokens[self.i+1].text == 'fun':
            self.take()
            return self.function(True)
        if self.peek('fun'):
            return self.function(False)
        if self.peek('if') or self.peek('while') or self.peek('for'):
            keyword = self.take().text
            condition = self.group()
            result = keyword + ' ' + condition + ':\n' + self.suite()
            if self.follow('else'):
                if keyword == 'if' and self.peek('if'):
                    result += '\nel' + self.statement()
                else:
                    result += '\nelse:\n' + self.suite()
            return result
        if self.peek('try'):
            self.take()
            result = 'try:\n' + self.suite()
            count = 0
            while self.follow('catch'):
                count += 1
                if self.peek('('):
                    self.take('(')
                    args = self.collect(stops=(')',), newline=False)
                    self.take(')')
                    if len(args) > 1 and args[0].kind == 'name' and args[1].text == ':':
                        clause = expr(args[2:]) + ' as ' + args[0].text
                    else:
                        clause = expr(args)
                    result += '\nexcept ' + clause + ':\n' + self.suite()
                else:
                    result += '\nexcept:\n' + self.suite()
            if self.follow('else'):
                result += '\nelse:\n' + self.suite()
            if self.follow('finally'):
                count += 1
                result += '\nfinally:\n' + self.suite()
            if not count:
                raise SyntaxErrorV2('try requires catch or finally')
            return result
        if self.peek('with'):
            self.take()
            return 'with ' + self.group() + ':\n' + self.suite()
        if self.peek('class'):
            self.take()
            header = expr(self.collect(stops=('{',), newline=False))
            self.val_scopes.append(set())
            body = self.suite()
            vals = self.val_scopes.pop()
            result = 'class ' + header + ':\n' + body
            validate_vals(result, vals)
            return result
        binding = self.take().text if self.peek('val') or self.peek('var') else None
        keyword = self.take().text if self.peek().text in ('return', 'throw', '=>') else None
        tokens = self.collect(stops=(';', '}'))
        expression = expr(tokens)
        if binding:
            try:
                nodes = ast.parse(expression).body
            except SyntaxError as exc:
                raise SyntaxErrorV2('Binding requires a Python-compatible assignment') from exc
            if len(nodes) != 1 or not isinstance(nodes[0], (ast.Assign, ast.AnnAssign)):
                raise SyntaxErrorV2('Binding requires an assignment')
            if binding == 'val':
                node = nodes[0]
                target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else getattr(node, 'target', None)
                if not isinstance(target, ast.Name) or getattr(node, 'value', None) is None:
                    raise SyntaxErrorV2('val requires one initialized name')
                if target.id in self.val_scopes[-1]:
                    raise SyntaxErrorV2(f'Duplicate val {target.id}')
                self.val_scopes[-1].add(target.id)
        if keyword:
            expression = ('raise' if keyword == 'throw' else 'return') + (' ' + expression if expression else '')
        if not expression:
            raise SyntaxErrorV2(f'Expected statement at line {t.line}')
        return expression

    def function(self, asynchronous):
        self.take('fun')
        name = self.take()
        if name.kind != 'name':
            raise SyntaxErrorV2('Expected function name')
        args = self.group()
        returns = ''
        if self.peek(':'):
            self.take()
            returns = ' -> ' + expr(self.collect(stops=('=', '=>', '{')))
        header = ('async def ' if asynchronous else 'def ') + name.text + '(' + args + ')' + returns
        self.separators()
        self.val_scopes.append(set())
        if self.peek('=') or self.peek('=>'):
            self.take()
            while self.peek().kind == 'newline':
                self.take()
            value = expr(self.collect(stops=(';', '}')))
            ast.parse(value, mode='eval')
            body = '    return ' + value
        else:
            body = self.suite()
        vals = self.val_scopes.pop()
        result = header + ':\n' + body
        validate_vals(result, vals)
        return result

    def units(self):
        units = []
        self.separators()
        while self.peek().kind != 'eof':
            start = self.peek().start
            python = self.statement() + '\n'
            end = self.tokens[self.i-1].end
            ast.parse(python)
            units.append((self.source[start:end], python))
            if self.peek().kind not in ('newline', 'eof') and not self.peek(';'):
                raise SyntaxErrorV2(f'Expected newline or semicolon at line {self.peek().line}')
            self.separators()
        validate_vals('\n'.join(p for _, p in units), self.val_scopes[0])
        return units


def validate_vals(source, names):
    """Conservative lexical check; rejects shadowing/writes in nested scopes too."""
    if not names:
        return
    tree = ast.parse(source)
    for name in names:
        writes = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del)):
                writes += 1
            elif isinstance(node, ast.arg) and node.arg == name:
                writes += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                writes += 1
            elif isinstance(node, ast.ExceptHandler) and node.name == name:
                writes += 1
            elif isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) == name:
                writes += 1
            elif isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names:
                raise SyntaxErrorV2(f'val {name} cannot be global/nonlocal')
        if writes != 1:
            raise SyntaxErrorV2(f'val {name} has another binding/write; use var')


def emit_expr(node):
    if isinstance(node, ast.JoinedStr) and any(isinstance(n, ast.FormattedValue) for n in node.values):
        if all(isinstance(n, ast.Constant) or (n.conversion == -1 and n.format_spec is None) for n in node.values):
            chunks = []
            for value in node.values:
                if isinstance(value, ast.Constant):
                    if '${' in value.value:
                        raise SyntaxErrorV2('Literal interpolation marker uses escape block')
                    chunks.append(json.dumps(value.value, ensure_ascii=False)[1:-1])
                else:
                    chunks.append('${' + emit_expr(value.value) + '}')
            return '"' + ''.join(chunks) + '"'
    if isinstance(node, ast.IfExp):
        return f'(if ({emit_expr(node.test)}) {emit_expr(node.body)} else {emit_expr(node.orelse)})'
    # Substitute nested conditionals without textual replacement of identifiers.
    class Surface(ast.NodeTransformer):
        def __init__(self):
            self.substitutions = {}
            self.names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        def visit_IfExp(self, item):
            name = '__pyfold_expr_' + str(len(self.substitutions))
            while name in self.names:
                name += '_'
            self.names.add(name)
            self.substitutions[name] = emit_expr(item)
            return ast.Name(id=name, ctx=ast.Load())
    import copy
    surface = Surface()
    text = ast.unparse(surface.visit(copy.deepcopy(node)))
    aliases = {'True':'true', 'False':'false', 'None':'null', 'and':'&&', 'or':'||', 'not':'!'}
    out, cursor, previous = [], 0, None
    # unparse expressions are normally one line; multiline output uses fallback.
    if '\n' in text:
        raise SyntaxErrorV2('Multiline expression uses Python escape block')
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type in (tokenize.ENDMARKER, tokenize.NEWLINE):
            continue
        start, end = token.start[1], token.end[1]
        out.append(text[cursor:start])
        replacement = token.string
        if token.type == tokenize.NAME:
            replacement = surface.substitutions.get(replacement, aliases.get(replacement, replacement) if previous != '.' else replacement)
        # Plain Python strings must never accidentally introduce interpolation.
        if token.type == tokenize.STRING and '${' in replacement and replacement.startswith('"'):
            replacement = repr(ast.literal_eval(replacement))
            if replacement.startswith('"'):
                replacement = 'r' + replacement if '\\' not in replacement else replacement
                raise SyntaxErrorV2('Literal interpolation marker uses escape block')
        out.append(replacement)
        previous, cursor = token.string, end
    return ''.join(out)


def emit_statement(node):
    def block(header, body):
        return header + ' {\n' + '\n'.join('    ' + line for stmt in body for line in emit_statement(stmt).splitlines()) + '\n}'
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.decorator_list or getattr(node, 'type_params', []):
            raise SyntaxErrorV2('Decorated/generic function uses escape block')
        header = ('async fun ' if isinstance(node, ast.AsyncFunctionDef) else 'fun ') + node.name + '(' + emit_expr(node.args) + ')'
        if node.returns:
            header += ': ' + emit_expr(node.returns)
        if len(node.body) == 1 and isinstance(node.body[0], ast.Return) and node.body[0].value is not None:
            return header + ' = ' + emit_expr(node.body[0].value)
        return block(header, node.body)
    if isinstance(node, ast.If):
        result = block('if (' + emit_expr(node.test) + ')', node.body)
        if node.orelse:
            result += (' else ' + emit_statement(node.orelse[0]) if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)
                       else ' else' + block('', node.orelse))
        return result
    if isinstance(node, (ast.For, ast.While)):
        condition = (emit_expr(node.target) + ' in ' + emit_expr(node.iter)) if isinstance(node, ast.For) else emit_expr(node.test)
        result = block(('for' if isinstance(node, ast.For) else 'while') + ' (' + condition + ')', node.body)
        if node.orelse:
            result += ' else' + block('', node.orelse)
        return result
    if isinstance(node, ast.Try):
        result = block('try', node.body)
        for handler in node.handlers:
            clause = (' (' + (handler.name + ': ' if handler.name else '') + emit_expr(handler.type) + ')') if handler.type else ''
            result += ' catch' + block(clause, handler.body)
        if node.orelse:
            result += ' else' + block('', node.orelse)
        if node.finalbody:
            result += ' finally' + block('', node.finalbody)
        return result
    if isinstance(node, ast.With):
        items = ', '.join(emit_expr(n.context_expr) + (' as ' + emit_expr(n.optional_vars) if n.optional_vars else '') for n in node.items)
        return block('with (' + items + ')', node.body)
    if isinstance(node, ast.ClassDef):
        if node.decorator_list or getattr(node, 'type_params', []):
            raise SyntaxErrorV2('Decorated/generic class uses escape block')
        bases = ', '.join([emit_expr(n) for n in node.bases] + [emit_expr(n) for n in node.keywords])
        return block('class ' + node.name + ('(' + bases + ')' if bases else ''), node.body)
    if isinstance(node, ast.Return):
        return 'return' + (' ' + emit_expr(node.value) if node.value is not None else '')
    if isinstance(node, ast.Raise):
        return 'throw' + (' ' + emit_expr(node.exc) if node.exc else '') + (' from ' + emit_expr(node.cause) if node.cause else '')
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        declaration = all(isinstance(t, (ast.Name, ast.Tuple, ast.List)) for t in targets)
        return ('var ' if declaration else '') + emit_expr(node)
    if isinstance(node, (ast.Expr, ast.AugAssign, ast.Assert, ast.Pass, ast.Break, ast.Continue, ast.Delete, ast.Global, ast.Nonlocal, ast.Import, ast.ImportFrom)):
        return emit_expr(node)
    raise SyntaxErrorV2(f'{type(node).__name__} uses Python escape block')
