"""Command line interface. Translation never executes the input program."""
import argparse
import json
import sys
from pathlib import Path

from .core import FoldError, fold, unfold


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
    check = sub.add_parser("check", help="verify exact round trip and standalone AST")
    check.add_argument("source")
    args = parser.parse_args()
    try:
        source = read(args.source)
        if args.command == "fold":
            view, metadata = fold(source)
            map_path = args.map_path or args.output + ".map.json"
            if len({Path(p).resolve() for p in (args.source, args.output, map_path)}) != 3:
                raise FoldError("Input, output, and sidecar must be different files")
            write(args.output, view)
            write(map_path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        elif args.command == "unfold":
            if Path(args.source).resolve() == Path(args.output).resolve():
                raise FoldError("Input and output must be different files")
            metadata = json.loads(read(args.map_path)) if args.map_path else None
            write(args.output, unfold(source, metadata))
        else:
            from .core import fingerprint
            view, metadata = fold(source)
            if unfold(view, metadata) != source:
                raise FoldError("Exact round trip failed")
            if fingerprint(unfold(view)) != fingerprint(source):
                raise FoldError("Standalone AST differs")
            print("OK: exact text round trip; standalone Python AST matches")
    except (FoldError, SyntaxError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"pyfold: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
