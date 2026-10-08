"""Many authoring files to many explicitly named Python modules."""
from __future__ import annotations

import ast
import json
from pathlib import Path, PurePosixPath

from .core import FoldError, fold, unfold
from .checking import check_pair, rebind
from .syntax import HEADER, Parser, SyntaxErrorV2, lex, matching

PROJECT_HEADER = '#!pyfold project 1'
IGNORED = {'.git', '.venv', 'venv', '__pycache__'}


def module_path(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value or '\x00' in value:
        raise FoldError('Module path must be a relative POSIX .py path')
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ('', '.', '..') for p in value.split('/')) or path.suffix != '.py':
        raise FoldError(f'Invalid module path: {value!r}')
    return value


def read_tree(root, suffix):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise FoldError(f'Expected a non-symlink directory: {root}')
    files = {}
    for path in sorted(root.rglob('*' + suffix)):
        relative = path.relative_to(root)
        if any(p in IGNORED for p in relative.parts):
            continue
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root.parent):
            raise FoldError(f'Symlink input is not supported: {relative}')
        if path.is_file():
            files[relative.as_posix()] = path.read_bytes().decode('utf-8')
    return files


def fragments(source, filename):
    if source.splitlines()[:1] != [PROJECT_HEADER]:
        raise FoldError(f'{filename}: expected {PROJECT_HEADER}')
    tokens, index = lex(source), 0
    found = []
    def skip():
        nonlocal index
        while tokens[index].kind == 'newline' or tokens[index].text == ';':
            index += 1
    def take(text=None):
        nonlocal index
        token = tokens[index]
        if token.kind == 'eof' or (text is not None and token.text != text):
            raise FoldError(f'{filename}:{token.line}: expected {text or "token"}')
        index += 1
        return token
    skip()
    while tokens[index].kind != 'eof':
        take('module')
        token = take()
        if token.kind != 'string':
            raise FoldError(f'{filename}:{token.line}: expected literal module path')
        path = module_path(ast.literal_eval(token.text))
        take('part')
        order = take()
        if order.kind != 'number' or not order.text.isdecimal():
            raise FoldError(f'{filename}:{order.line}: part must be a nonnegative integer')
        skip()
        opening = index
        brace = take('{')
        end = matching(tokens, opening)
        body = source[brace.end:tokens[end].start].strip('\r\n')
        # Each fragment must contain complete top-level statements. Module-level
        # compile and val validation happen again after all fragments are assembled.
        Parser(HEADER + '\n' + body).units()
        found.append((path, int(order.text), body, filename))
        index = end + 1
        skip()
    return found


def assemble(views):
    modules, aliases = {}, {}
    try:
        for filename in sorted(views):
            for path, order, body, origin in fragments(views[filename], filename):
                alias = path.casefold()
                if alias in aliases and aliases[alias] != path:
                    raise FoldError(f'Case-colliding module paths: {aliases[alias]} and {path}')
                aliases[alias] = path
                parts = modules.setdefault(path, {})
                if order in parts:
                    raise FoldError(f'Duplicate module part {path}:{order} in {parts[order][1]} and {origin}')
                parts[order] = (body, origin)
        for path in modules:
            if any(str(parent).casefold() in aliases for parent in PurePosixPath(path).parents):
                raise FoldError(f'Module path conflicts with a parent file: {path}')
        result = {path: HEADER + '\n' + '\n\n'.join(parts[n][0] for n in sorted(parts)) + '\n'
                  for path, parts in sorted(modules.items())}
        # Entire module compilation validates future imports and cross-part scope.
        for view in result.values():
            unfold(view)
        return result
    except (SyntaxErrorV2, SyntaxError, ValueError) as exc:
        if isinstance(exc, FoldError):
            raise
        raise FoldError(str(exc)) from exc


def fold_project(sources):
    views, maps = {}, {}
    for path, source in sorted(sources.items()):
        module_path(path)
        _, sidecar = fold(source)
        sections = [f'module {json.dumps(path)} part {i * 10} {{\n{unit["view"]}\n}}'
                    for i, unit in enumerate(sidecar['units'])]
        views[path[:-3] + '.fold'] = PROJECT_HEADER + '\n' + '\n\n'.join(sections) + '\n'
        maps[path] = sidecar
    assemble(views)
    return views, {'kind': 'pyfold-project', 'version': 1, 'modules': maps}


def validate_map(metadata):
    if not isinstance(metadata, dict) or metadata.get('kind') != 'pyfold-project' or metadata.get('version') != 1:
        raise FoldError('Invalid project map kind/version')
    modules = metadata.get('modules')
    if not isinstance(modules, dict):
        raise FoldError('Project map modules must be an object')
    for path in modules:
        module_path(path)
    return modules


def expand_project(views, metadata=None):
    modules = assemble(views)
    maps = validate_map(metadata) if metadata is not None else None
    if maps is not None and set(modules) != set(maps):
        raise FoldError(f'Project/map module sets differ: missing={sorted(set(maps)-set(modules))}, extra={sorted(set(modules)-set(maps))}')
    return {path: unfold(view, maps[path] if maps is not None else None) for path, view in modules.items()}


def check_project(views, metadata, original=None):
    result = {'ok': False, 'module_set_matches_map': False,
              'original_file_set_matches': None, 'modules': {}, 'diagnostics': []}
    try:
        modules, maps = assemble(views), validate_map(metadata)
        result['module_set_matches_map'] = set(modules) == set(maps)
        if not result['module_set_matches_map']:
            result['diagnostics'].append(f'Map mismatch: missing={sorted(set(maps)-set(modules))}, extra={sorted(set(modules)-set(maps))}')
        if original is not None:
            result['original_file_set_matches'] = set(modules) == set(original)
            if not result['original_file_set_matches']:
                result['diagnostics'].append(f'Original mismatch: missing={sorted(set(original)-set(modules))}, extra={sorted(set(modules)-set(original))}')
        for path, view in modules.items():
            if path in maps:
                result['modules'][path] = check_pair(view, maps[path], original.get(path) if original is not None else None)
        result['ok'] = result['module_set_matches_map'] and result['original_file_set_matches'] is not False and all(
            value['ok'] for value in result['modules'].values())
    except (FoldError, SyntaxError, ValueError, TypeError) as exc:
        result['diagnostics'].append(str(exc))
    return result


def rebind_project(views, original):
    modules = assemble(views)
    if set(modules) != set(original):
        raise FoldError('Cannot rebind: expanded module paths differ from original Python paths')
    return {'kind': 'pyfold-project', 'version': 1,
            'modules': {path: rebind(view, original[path]) for path, view in modules.items()}}


def write_tree(root, files, inputs=()):
    root = Path(root)
    resolved = root.resolve()
    for input_path in inputs:
        source = Path(input_path).resolve()
        if resolved == source or resolved in source.parents or source in resolved.parents:
            raise FoldError('Output directory must be disjoint from input directories')
    if root.is_symlink() or (root.exists() and (not root.is_dir() or any(root.iterdir()))):
        raise FoldError('Output directory must be new or empty; refusing to overwrite existing files')
    # Validate all destinations before the first write.
    for relative in files:
        path = PurePosixPath(relative)
        if path.is_absolute() or any(p in ('', '.', '..') for p in relative.split('/')) or '\\' in relative:
            raise FoldError(f'Unsafe output path: {relative}')
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode('utf-8'))


def project_cli(args):
    if args.operation == 'fold':
        views, metadata = fold_project(read_tree(args.source, '.py'))
        views['project.map.json'] = json.dumps(metadata, ensure_ascii=False, indent=2) + '\n'
        write_tree(args.output, views, [args.source])
    else:
        views = read_tree(args.source, '.fold')
        if args.operation == 'unfold':
            metadata = json.loads(Path(args.map_path).read_text()) if args.map_path else None
            files = expand_project(views, metadata)
            write_tree(args.output, files, [args.source])
        elif args.operation == 'check':
            metadata = json.loads(Path(args.map_path).read_text())
            original = read_tree(args.against, '.py') if args.against else None
            result = check_project(views, metadata, original)
            if args.json_output:
                print(json.dumps(result, ensure_ascii=False))
            else:
                print('PASS' if result['ok'] else 'FAIL')
                for path, checks in result['modules'].items():
                    print(path + ': ' + ('PASS' if checks['ok'] else 'FAIL'))
                    for diagnostic in checks['diagnostics']:
                        print('  ' + diagnostic)
                for diagnostic in result['diagnostics']:
                    print(diagnostic)
            return 0 if result['ok'] else 1
        else:
            metadata = rebind_project(views, read_tree(args.against, '.py'))
            output = Path(args.output).resolve()
            original_root = Path(args.against).resolve()
            if output == original_root or original_root in output.parents or output.suffix != '.json':
                raise FoldError('Rebind output must be a .json file outside the original tree')
            Path(args.output).write_bytes((json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode())
    return 0
