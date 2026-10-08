"""Command line interface. Translation never executes the input program."""
import argparse
import json
import sys
from pathlib import Path

from .core import FoldError, fold, unfold
from .checking import check_pair, rebind


def read(path):
    return Path(path).read_bytes().decode("utf-8")


def write(path, text):
    Path(path).write_bytes(text.encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(prog="pyfold")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("fold", "unfold"):
        command = sub.add_parser(name)
        command.add_argument("source")
        command.add_argument("-o", "--output", required=True)
        command.add_argument("--map", dest="map_path")
        if name == 'fold':
            command.add_argument('--legacy', action='store_true', help='emit v1 syntax')
    check = sub.add_parser("check", help="verify exact round trip and standalone AST")
    check.add_argument("source")
    check.add_argument('--map', dest='map_path', help='validate an edited view/map pair')
    check.add_argument('--against', help='independent original Python source')
    check.add_argument('--json', action='store_true', dest='json_output')
    bind = sub.add_parser('rebind', help='generate sidecar for an equivalent alternate view')
    bind.add_argument('source')
    bind.add_argument('--against', required=True)
    bind.add_argument('-o', '--output', required=True)
    project = sub.add_parser('project', help='many-to-many project translation')
    operations = project.add_subparsers(dest='operation', required=True)
    for name in ('fold', 'unfold', 'check', 'rebind'):
        operation = operations.add_parser(name)
        operation.add_argument('source', help='input directory')
        if name != 'check':
            operation.add_argument('-o', '--output', required=True)
        if name in ('unfold', 'check'):
            operation.add_argument('--map', dest='map_path', required=name == 'check')
        if name in ('check', 'rebind'):
            operation.add_argument('--against', required=name == 'rebind')
        if name == 'check':
            operation.add_argument('--json', action='store_true', dest='json_output')
    args = parser.parse_args()
    try:
        if args.command == 'project':
            from .project import project_cli
            return project_cli(args)
        from .project import project_cli, has_module_blocks
        if Path(args.source).is_dir():
            if getattr(args, 'legacy', False):
                raise FoldError('--legacy is only supported for a single Python file')
            if args.command == 'fold' and args.map_path:
                raise FoldError('Directory conversion writes project.map.json inside the output directory')
            args.operation = args.command
            return project_cli(args)
        source = read(args.source)
        if args.command != 'fold' and Path(args.source).suffix == '.fold':
            metadata = json.loads(read(args.map_path)) if getattr(args, 'map_path', None) else None
            if has_module_blocks(source) or (isinstance(metadata, dict) and metadata.get('kind') == 'pyfold-project'):
                args.operation = args.command
                return project_cli(args)
        if args.command == "fold":
            view, metadata = fold(source, legacy=args.legacy)
            map_path = args.map_path or args.output + ".map.json"
            if len({Path(p).resolve() for p in (args.source, args.output, map_path)}) != 3:
                raise FoldError("Input, output, and sidecar must be different files")
            write(args.output, view if args.legacy else view.removeprefix('#!pyfold 2\n'))
            write(map_path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        elif args.command == "unfold":
            if Path(args.source).resolve() == Path(args.output).resolve():
                raise FoldError("Input and output must be different files")
            metadata = json.loads(read(args.map_path)) if args.map_path else None
            write(args.output, unfold(source, metadata))
        elif args.command == 'rebind':
            if Path(args.output).resolve() in (Path(args.source).resolve(), Path(args.against).resolve()):
                raise FoldError('Sidecar output must not overwrite view or original')
            metadata = rebind(source, read(args.against))
            write(args.output, json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
        elif args.map_path:
            result = check_pair(source, json.loads(read(args.map_path)), read(args.against) if args.against else None)
            if args.json_output:
                print(json.dumps(result, ensure_ascii=False))
            else:
                for key in ('pair_consistent', 'original_ast_matches', 'exact_reconstruction'):
                    value = result[key]
                    print(f'{key}: ' + ('not checked' if value is None else 'PASS' if value else 'FAIL'))
                for diagnostic in result['diagnostics']:
                    print(diagnostic)
            return 0 if result['ok'] else 1
        else:
            if args.against:
                raise FoldError('--against requires --map')
            from .core import fingerprint
            view, metadata = fold(source)
            if unfold(view, metadata) != source:
                raise FoldError("Exact round trip failed")
            if fingerprint(unfold(view)) != fingerprint(source):
                raise FoldError("Standalone AST differs")
            print(json.dumps({'ok': True, 'exact_reconstruction': True, 'original_ast_matches': True}) if args.json_output
                  else "OK: exact text round trip; standalone Python AST matches")
    except (FoldError, SyntaxError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        if getattr(args, 'json_output', False):
            print(json.dumps({'ok': False, 'diagnostics': [str(exc)]}))
        else:
            print(f"pyfold: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
