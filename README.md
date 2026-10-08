# PyFold

**Re-express Python's intent, with deterministic expansion and exact source reconstruction.**

PyFold is a TypeScript/Kotlin-inspired authoring surface that executes as Python.
The fast deterministic converter provides a baseline. A human or LLM can choose a
clearer representation, then verify it against independent original Python.
Shorter is optional; understandable and checkable are the goals.

Two layers:

- `.fold`: the standalone program. Braces delimit blocks; indentation is cosmetic.
- `.fold.map.json`: optional original-source reconstruction data, never hidden semantics.

```text
fun greet(name: str, excited: bool = false): str {
    val suffix = if (excited) "!" else "."
    return "Hello, ${name}${suffix}"
}

fun active_names(users) =
    [user.name.strip() for (user in users) if (user.active)]
```

## Try it

Python 3.11+; no runtime dependencies. Run from this checkout:

```sh
python -m pyfold fold examples/original.py -o examples/original.fold
python -m pyfold unfold examples/original.fold --map examples/original.fold.map.json -o restored.py
python -m pyfold check examples/original.fold --map examples/original.fold.map.json --against examples/original.py --json
python -m unittest discover -s tests -v
```

Or `python -m pip install -e .` for the `pyfold` command. Translation parses and
compiles for validation but never executes the input. Do not run untrusted
programs merely to translate them.

The converter is deterministic for fixed input, PyFold version and Python version.
It attempts supported surface constructs and checks their expanded AST. Unsupported
or mismatching constructs fall back to explicit fenced Python. No LLM is needed.

## The authoring loop

1. Convert original Python with `fold`.
2. Keep the original independent and unchanged.
3. Edit the view to make intent clearer, using supported representations.
4. Check the edited view with `--map` and `--against`.
5. Optionally generate a fresh map with `rebind`.

```sh
python -m pyfold rebind examples/readable.fold --against examples/original.py -o readable.map.json
python -m pyfold check examples/readable.fold --map readable.map.json --against examples/original.py --json
```

`examples/readable.fold` deliberately differs from the converter's output: it uses
`val`, parenthesized generator clauses, alternative function bodies, and a compact
class layout. It still expands to the original AST and reconstructs exact source.

The JSON checker reports:

| Field | Meaning |
| --- | --- |
| `pair_consistent` | Valid map; standalone expansion and reconstructed Python have the same AST |
| `original_ast_matches` | Expanded view has the same AST as the independent original |
| `exact_reconstruction` | Reconstruction equals the original text, including line endings |
| `ok` | All requested checks pass; process exits 0, otherwise 1 |

Without `--against`, the last two checks are `null` (not checked). Pair consistency
alone does **not** prove original preservation: two edited files can agree on the
wrong program. `check input.py` remains available for the original converter
round-trip check. `rebind` refuses a changed AST and never edits the original or view.
Character counts are informational, not an optimization objective.

See [AUTHORING.md](AUTHORING.md) for the human/LLM workflow.

## Many-to-many projects

One PyFold file can contain fragments from multiple Python modules, and one Python
module can be assembled from multiple PyFold files. Unwrapped code defaults to its
relative filename (`app/users.fold` → `app/users.py`). Module blocks can occur in any
file and contribute to those same modules across the input tree:

```text
#!pyfold 1
module "app/users.py" part 10 {
    fun find_user(id) = PREFIX + str(id)
}
module "app/orders.py" part 20 {
    fun order_for_user(id) = find_user(id)
}
```

```sh
python -m pyfold fold python-src -o authoring
python -m pyfold check authoring --map authoring/project.map.json --against python-src --json
python -m pyfold unfold authoring --map authoring/project.map.json -o restored-python
```

Move complete fragments between `.fold` files freely. Their module identity and
part order stay fixed regardless of authoring filename. The checker validates the
full Python path set and each module's AST/exact reconstruction. See
[PROJECTS.md](PROJECTS.md) for commands, limits and a working many-to-many example.

## Syntax and semantics

| Surface | Python expansion / contract |
| --- | --- |
| `fun f(x): T { ... }` | `def f(x) -> T: ...` |
| `fun f(x) = expression` | Function returning the expression; `=>` is also accepted |
| `async fun f(x) = await x` | Python async function/coroutine |
| `var x = value` | Ordinary Python assignment; does not add scope |
| `val x = value` | Assignment with a conservative static no-rebinding check |
| `if (c) { ... } else if (d) { ... } else { ... }` | Python if/elif/else |
| `for (x in xs) { ... }`, `while (c) { ... }` | Python loops, including loop-variable scope; loop `else` supported |
| `try { ... } catch (e: Error) { ... } finally { ... }` | Python try/except/finally; bare catch and try/else supported |
| `with (open(path) as file) { ... }` | Python context manager |
| `class C(Base) { ... }` | Python class; methods use `fun` and explicit `self` |
| `throw e`, `throw e from cause`, `throw` | `raise` forms, preserving exception chaining |
| `if (c) a else b` | Python conditional expression; parenthesize inside larger expressions |
| `true`, `false`, `null`, `&&`, `\|\|`, `!` | Python `True`, `False`, `None`, `and`, `or`, `not` |
| `"Hello, ${name}"` | Python f-string, preserving expression evaluation |

Statements are separated by newlines or semicolons. Braces, not indentation, define
blocks. Multiline expressions go inside `()`, `[]` or `{}`. Use `#` line comments or
`/* block comments */`; `//` remains Python floor division. Newly authored surface
comments aren't copied into canonical Python. The map preserves original comments.
Single-quoted strings are literal; unprefixed double-quoted strings support `${…}`.
Python string prefixes are also accepted. Advanced f-string formatting may remain
in Python f-string notation or fall back to a fenced block.

Operators retain **Python precedence and behavior**, including `!a == b` meaning
`!(a == b)`, short-circuit operand values, arbitrary-precision integers and false
empty collections. Parenthesize explicitly if that precedence is surprising.
Expressions, annotations, calls, defaults, dictionaries, comprehensions and imports
otherwise retain Python grammar. Comprehension `for (x in xs)` is also accepted.
This is not full TypeScript or Kotlin compatibility and includes no type checker.

`val` does not freeze objects. Its check rejects additional writes, deletion,
shadowing in nested scopes, imports and global/nonlocal declarations of the name.
It is deliberately conservative; use `var` for Python patterns it rejects. Dynamic
writes via reflection/exec are not prevented. Automatic conversion emits `var`
for bindings rather than trying to infer immutability.

## Losslessness and limits

An unchanged pair reconstructs original UTF-8 source exactly, including comments,
quote style, CRLF, and missing final newline. An alternate view with the **same
whole-module AST** also reconstructs the exact original, even when its units are
formatted or grouped differently. Ordinary semantic edits regenerate changed
units and preserve matching original fragments where possible.

AST equality is a concrete structural contract, **not a general proof of behavioral
equivalence**. The checker intentionally rejects behavior-preserving rewrites that
produce different ASTs. It does not promise equivalent source inspection, tracing,
tracebacks or type-checker behavior without original-source restoration. Sidecar
checksums are consistency checks, not signatures or trust boundaries.

Rebinding stores one whole-module reconstruction recipe. Subsequent semantic edits
to a rebound pair can lose original comments because finer-grained matches are no
longer available. The checker will report failed exact reconstruction. The converter
still creates per-top-level-unit recipes. No stable node identities or concurrent
bidirectional merge are implemented.

Decorators, pattern matching, async loops/context managers, and other unsupported
constructs remain editable in fenced `python` blocks. Python inside those blocks
retains Python indentation rules. UTF-8 BOM and other encodings are not supported.

V1 files and sidecars remain readable. `fold --legacy` emits the original `fn` syntax.
Headers are optional; new output omits them. Earlier headers remain accepted.

No user-defined macros, `retry` construct, automatic temporary-name abstraction or
loop compression are implemented yet. New representations must have explicit,
deterministic expansion rules; hidden sidecar code is not an acceptable substitute.
See [DESIGN.md](DESIGN.md).
