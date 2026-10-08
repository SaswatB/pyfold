# PyFold

A working experiment in **one program, two layers**:

1. `.fold`: a compact, standalone authoring view with Python semantics.
2. `.fold.map.json`: optional original source and reconstruction information.

The sidecar restores presentation; it must not secretly change the program.
This is a small prototype, not a complete TypeScript-like language or a claim
that arbitrary Python can be safely compressed into functional expressions.

## Try it

Python 3.11+; no runtime dependencies. Run from this checkout:

```sh
python -m pyfold fold examples/original.py -o examples/original.fold
python -m pyfold unfold examples/original.fold --map examples/original.fold.map.json -o restored.py
python -m pyfold check examples/original.py
python -m unittest discover -s tests -v
```

Or install with `python -m pip install -e .` to get the `pyfold` command.
The translator parses and compiles for validation but never executes input.

## Authoring syntax

```text
fn active_names(users) => [user.name.strip() for user in users if user.active]

fn greet(name: str, excited: bool = False) -> str {
    let suffix = '!' if excited else '.'
    => f'Hello, {name}{suffix}'
}

fn once(fetch, consume) {
    let value = fetch()
    => consume(value, value)
}

async fn resolve(task) => await task
```

`fn ... => expression` is a Python function returning that expression.
Braced functions contain one simple Python statement per line. `let` is optional
assignment sugar, not a new lexical scope; `=>` in the body means `return`.
Function closing braces occupy their own unindented line. Expressions, types,
keyword arguments, booleans, comprehensions and operators remain **Python**.
There are no JavaScript runtime semantics. Top-level `//` view comments are
non-executable and are not copied into generated Python.

Unsupported constructs remain visible in fenced `python` blocks. The exporter
chooses a longer fence if the source contains backticks. These blocks can be
edited directly and may contain arbitrary Python supported by your interpreter.
Decorated functions, classes and compound function bodies currently use this
escape hatch. Same-line top-level statements cause whole-file fallback.

## Reconstruction contract

| Operation | Behavior |
| --- | --- |
| Fold, then unfold with unchanged view and sidecar | Exact original UTF-8 text, including CRLF, comments and missing final newline |
| Unfold without a sidecar | Canonical executable Python |
| Edit a function | Regenerate that function; preserve AST-equivalent untouched units |
| Add, delete or reorder units | Reflect the new program; reuse matching original fragments |
| Corrupt source checksum or inconsistent source/view in map | Reject instead of restoring different code |

The compiler checks each restored fragment and the edited whole module against
the standalone view using Python AST equality. This preserves ordinary Python
execution structure, including evaluation order, bindings and default argument
timing. **It does not preserve tracebacks, line numbers, source inspection,
tracing behavior, type-checker directives or every possible reflective
observation after edits or standalone compilation.** Untouched exact round trips
retain those original source details.

The sidecar is deliberately redundant: it caches original source. It is not
encryption, a security boundary, or a space-saving format. Commit it alongside
the view if you need reconstruction. Neither file is trusted for execution.

Current matching is by AST-equivalent top-level fragments, consuming duplicates
in order. The `id` fields are reserved bookkeeping, **not stable edit identities**.
Leading comments follow a reused fragment; comments attached to changed/deleted
fragments can be lost. Tail comments are retained. The prototype does not merge
concurrent edits to Python and the view. Re-fold the authoritative Python to
refresh the sidecar, or keep editing the view against its original sidecar.

## Why temporary names are not hidden yet

The first slice proves standalone compilation and reversible presentation.
It does not yet deliver the largest expected concision improvements. A binding
such as `value = fetch()` remains explicit because it means evaluate once.
Python also exposes binding names through `locals()`, frames and tracing.

The next useful step is a symbol-aware intermediate representation, with
explicit effect/evaluation order, followed by conservative pattern compression.
For example, an accumulator loop cannot automatically become a comprehension:
loop variable scope, observable locals and callbacks can expose differences.
Only patterns with a documented equivalence contract should be folded.

See [DESIGN.md](DESIGN.md) for the extension plan.

## Status

Implemented: import/export CLI, expression functions, simple braced functions,
Python escape blocks, source-cache sidecars, partial reconstruction, AST guards,
examples and standard-library unit tests. CI is configured for Python 3.11–3.13.
Local validation was performed on Python 3.12.

Not implemented: a type checker, editor/LSP integration, stable syntax-tree
identities, fine-grained comment merging, automatic temporary-name abstraction,
loop compression, whole-project imports, non-UTF-8 source or a sandbox for running
generated programs. UTF-8 BOM source is currently rejected.
