"""Deliberately conservative, standard-library-only prototype.

The sidecar is a source cache, never an alternate source of executable meaning.
Every restored fragment must have the same Python AST as its current view.
"""
from __future__ import annotations

import ast
import hashlib
import io
import re
import tokenize
from dataclasses import dataclass
from .syntax import HEADER, Parser, SyntaxErrorV2, emit_statement


class FoldError(ValueError):
    """Invalid source, authoring syntax, or reconstruction data."""


def fingerprint(source: str) -> str:
    try:
        return ast.dump(ast.parse(source), include_attributes=False)
    except SyntaxError as exc:
        raise FoldError(f"Invalid Python at line {exc.lineno}: {exc.msg}") from exc


def digest(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def raw_view(source: str) -> str:
    fence = "```"
    while fence in source:
        fence += "`"
    return fence + "python\n" + source.rstrip("\r\n") + "\n" + fence


def function_view(node: ast.AST) -> str | None:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    if node.decorator_list or getattr(node, "type_params", []):
        return None
    # Compound statements and multiline literals use the visible escape hatch.
    allowed = (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr,
               ast.Return, ast.Raise, ast.Assert, ast.Pass, ast.Delete,
               ast.Global, ast.Nonlocal, ast.Import, ast.ImportFrom)
    if any(not isinstance(stmt, allowed) for stmt in node.body):
        return None
    prefix = "async fn " if isinstance(node, ast.AsyncFunctionDef) else "fn "
    signature = prefix + node.name + "(" + ast.unparse(node.args) + ")"
    if node.returns:
        signature += " -> " + ast.unparse(node.returns)
    if "\n" in signature:
        return None
    if len(node.body) == 1 and isinstance(node.body[0], ast.Return):
        value = node.body[0].value
        return signature + " => " + (ast.unparse(value) if value else "None")
    lines = []
    for stmt in node.body:
        rendered = ast.unparse(stmt)
        if "\n" in rendered:
            return None
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            rendered = "let " + rendered
        elif isinstance(stmt, ast.Return) and stmt.value:
            rendered = "=> " + ast.unparse(stmt.value)
        lines.append("    " + rendered)
    return signature + " {\n" + "\n".join(lines) + "\n}"


@dataclass
class Unit:
    view: str
    python: str


def _header(line: str) -> tuple[str, str, str]:
    """Find the outer => or { with Python's tokenizer, not string splitting."""
    prefix = "async def " if line.startswith("async fn ") else "def "
    rest = line[len("async fn ") if line.startswith("async fn ") else 3:]
    depth = 0
    previous = None
    try:
        for token in tokenize.generate_tokens(io.StringIO(rest).readline):
            text = token.string
            if token.type != tokenize.OP:
                previous = None
                continue
            if depth == 0 and text == "{" and rest[token.end[1]:].strip() == "":
                return prefix + rest[:token.start[1]].rstrip(), "block", ""
            if depth == 0 and text == ">" and previous is not None:
                if previous.string == "=" and previous.end == token.start:
                    return (prefix + rest[:previous.start[1]].rstrip(),
                            "expr", rest[token.end[1]:].strip())
            if text in ("(", "[", "{"):
                depth += 1
            elif text in (")", "]", "}"):
                depth -= 1
            previous = token
    except (tokenize.TokenError, IndentationError) as exc:
        raise FoldError(f"Invalid function header: {line}") from exc
    raise FoldError(f"Expected => expression or opening brace: {line}")


def parse(view: str) -> list[Unit]:
    if view.startswith(HEADER) or re.match(r'\s*(?:async\s+)?fun\s', view):
        try:
            return [Unit(v, p) for v, p in Parser(view).units()]
        except (SyntaxErrorV2, SyntaxError) as exc:
            raise FoldError(str(exc)) from exc
    lines = view.splitlines()
    units = []
    i = 0
    while i < len(lines):
        if not lines[i].strip() or lines[i].lstrip().startswith("//"):
            i += 1
            continue
        start = i
        line = lines[i]
        match = re.fullmatch(r"(`{3,})python", line)
        if match:
            fence = match.group(1)
            i += 1
            body = []
            while i < len(lines) and lines[i] != fence:
                body.append(lines[i])
                i += 1
            if i == len(lines):
                raise FoldError(f"Unclosed Python block at line {start + 1}")
            python = "\n".join(body) + "\n"
        elif line.startswith(("fn ", "async fn ")):
            header, kind, expr = _header(line)
            if kind == "expr":
                if not expr:
                    raise FoldError(f"Missing expression at line {i + 1}")
                # Validate as expression first: no semicolon statement injection.
                try:
                    ast.parse(expr, mode="eval")
                except SyntaxError as exc:
                    raise FoldError(f"Invalid expression at line {i + 1}") from exc
                python = header + ":\n    return " + expr + "\n"
            else:
                i += 1
                body = []
                while i < len(lines) and lines[i] != "}":
                    stmt = lines[i].strip()
                    if stmt.startswith("let "):
                        stmt = stmt[4:]
                        try:
                            parsed = ast.parse(stmt).body
                        except SyntaxError as exc:
                            raise FoldError(f"Invalid binding at line {i + 1}") from exc
                        if len(parsed) != 1 or not isinstance(parsed[0], (ast.Assign, ast.AnnAssign)):
                            raise FoldError(f"let requires an assignment at line {i + 1}")
                    elif stmt.startswith("=> "):
                        stmt = "return " + stmt[3:]
                    if stmt:
                        body.append("    " + stmt)
                    i += 1
                if i == len(lines):
                    raise FoldError(f"Unclosed function at line {start + 1}")
                python = header + ":\n" + "\n".join(body or ["    pass"]) + "\n"
            tree = ast.parse(python)
            if len(tree.body) != 1 or not isinstance(tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
                raise FoldError("A function unit must contain exactly one function")
        else:
            raise FoldError(f"Expected fn or fenced Python at line {i + 1}")
        fingerprint(python)
        units.append(Unit("\n".join(lines[start:i + 1]), python))
        i += 1
    return units


def fold(source: str, *, legacy: bool = False) -> tuple[str, dict]:
    """Return authoring text and JSON-serializable reconstruction data.

    Exact text preservation includes newline style, comments and final newline.
    The CLI supports UTF-8 without BOM; other byte encodings are excluded.
    """
    fingerprint(source)
    try:
        compile(source, "<pyfold>", "exec")
    except SyntaxError as exc:
        raise FoldError(f"Invalid Python program: {exc.msg}") from exc
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    records = []
    cursor = 0
    # Same-line top-level statements have overlapping line spans; retain whole file.
    overlapping = any(a.end_lineno >= b.lineno for a, b in zip(tree.body, tree.body[1:]))
    if overlapping or not tree.body:
        chunks = [(0, len(lines), None)]
    else:
        chunks = [(min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])]) - 1,
                   n.end_lineno, n) for n in tree.body]
    for start, end, node in chunks:
        original = "".join(lines[start:end])
        try:
            candidate = function_view(node) if legacy else emit_statement(node)
        except (SyntaxErrorV2, TypeError, AttributeError, ValueError):
            candidate = None
        if candidate:
            try:
                expanded = parse(candidate if legacy else HEADER + '\n' + candidate)
                if fingerprint(''.join(u.python for u in expanded)) != fingerprint(original):
                    candidate = None
            except (FoldError, SyntaxError):
                candidate = None
        view = candidate or raw_view(original)
        records.append({"id": f"u{len(records)}", "view": view,
                        "source": original, "leading": "".join(lines[cursor:start])})
        cursor = end
    view = ('' if legacy else HEADER + '\n') + "\n\n".join(r["view"] for r in records) + "\n"
    return view, {"version": 1 if legacy else 2, "source_sha256": digest(source),
                  "view": view, "units": records, "trailing": "".join(lines[cursor:])}


def _validate_map(sidecar: dict) -> str:
    try:
        if not isinstance(sidecar, dict):
            raise FoldError("Sidecar must be an object")
        if sidecar["version"] not in (1, 2):
            raise FoldError("Unsupported sidecar version")
        records = sidecar["units"]
        if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
            raise FoldError("Sidecar units must be an array of objects")
        if not all(isinstance(r.get(k), str) for r in records for k in ("view", "source", "leading")):
            raise FoldError("Sidecar fragment fields must be strings")
        original = "".join(r["leading"] + r["source"] for r in records) + sidecar["trailing"]
        if digest(original) != sidecar["source_sha256"]:
            raise FoldError("Sidecar source checksum mismatch")
        prefix = HEADER + '\n' if sidecar['version'] == 2 else ''
        expected = prefix + "\n\n".join(r["view"] for r in records) + "\n"
        if expected != sidecar["view"]:
            raise FoldError("Sidecar view mismatch")
        for record in records:
            units = parse(prefix + record["view"])
            if fingerprint(''.join(u.python for u in units)) != fingerprint(record["source"]):
                raise FoldError("Sidecar would change program semantics")
        fingerprint(original)
        return original
    except (KeyError, TypeError) as exc:
        raise FoldError("Malformed sidecar") from exc


def unfold(view: str, sidecar: dict | None = None) -> str:
    """Compile standalone, or restore AST-equivalent original source fragments.

    A changed function is regenerated as a whole. Exact matching fragments retain
    original text, including duplicates consumed in order. Structural edits may
    move/drop attached comments; this prototype does not claim stable tree IDs.
    """
    units = parse(view)
    canonical = '\n'.join(unit.python for unit in units)
    try:
        compile(canonical, '<pyfold>', 'exec')
    except SyntaxError as exc:
        raise FoldError(f'Invalid compiled program: {exc.msg}') from exc
    if sidecar is None:
        result = "\n".join(unit.python for unit in units)
    else:
        original = _validate_map(sidecar)
        if fingerprint(canonical) == fingerprint(original):
            return original
        remaining = list(sidecar["units"])
        pieces = []
        for unit in units:
            shape = fingerprint(unit.python)
            match = next((r for r in remaining if fingerprint(r["source"]) == shape), None)
            if match is not None:
                remaining.remove(match)
                piece = match["leading"] + match["source"]
            else:
                piece = unit.python
            if pieces and not pieces[-1].endswith(("\n", "\r")):
                pieces.append("\n")
            pieces.append(piece)
        result = "".join(pieces) + sidecar["trailing"]
        # Final whole-module check catches interaction across reconstructed units.
        canonical = "\n".join(unit.python for unit in units)
        if fingerprint(result) != fingerprint(canonical):
            raise FoldError("Reconstruction differs from standalone program")
    fingerprint(result)
    try:
        compile(result, "<pyfold>", "exec")
    except SyntaxError as exc:
        raise FoldError(f"Invalid compiled program: {exc.msg}") from exc
    return result
