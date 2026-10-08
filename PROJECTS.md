# Modules across files

Use the same language and commands for a file or a directory. No mode or header is
needed. Any authoring file can contain ordinary declarations, explicit module
blocks, or both. The compiler collects module contributions across every supplied
`.fold` file before expanding Python.

Ordinary code gets its module from the relative authoring path:

```text
# app/users.fold → app/users.py
val PREFIX = 'user:'
```

An explicit declaration in any other file contributes to that same module:

```text
# features.fold
module "app/users.py" part 10 {
    fun find_user(id) = PREFIX + str(id)
}
module "app/orders.py" {
    from .users import find_user
    fun order_for_user(id) = find_user(id)
}
```

`app/users.fold` doesn't need a declaration, setting, or header because another file
contributes a module block. The result is `app/users.py` with its global followed by
its function, plus `app/orders.py`. There is no `features.py` unless that file also
contains unwrapped code. Explicit blocks affect only their contents, never silently
reassign neighboring or unrelated code to another module.

## Ordering

Unwrapped statements in a file form part 0 of its implicit module, preserving their
source order. Explicit blocks default to part 0; use `part N` to specify ordering
when a module has several contributions. Part numbers are unique nonnegative
integers per module and are sorted numerically. Gaps are allowed. Duplicate parts
are errors; the compiler doesn't guess order from filenames or scan order.

An explicit block extending an implicit module therefore uses a different part,
usually `part 10`. To put something before unwrapped code, move that code into a
block with a later part number. Moving explicit blocks between files preserves
module identity and order. Moving unwrapped code changes its default module with
its filename. Each contribution contains complete top-level statements; splitting
inside a function or class is not implemented.

Imports, globals and initialization remain in the assembled Python module. Relative
imports and packages use normal Python execution semantics. No automatic import
rewriting or new cross-module initialization order is introduced. The compiler
checks the assembled module, including future-import placement and cross-part `val`
constraints.

## Commands

```sh
# A deterministic baseline: ordinary files, no wrappers or headers.
python -m pyfold fold python-src -o authoring

# Validate file sets, expanded ASTs, and exact source reconstruction.
python -m pyfold check authoring --map authoring/project.map.json --against python-src --json

# Compile from the visible source, or restore with metadata.
python -m pyfold unfold authoring -o canonical-python
python -m pyfold unfold authoring --map authoring/project.map.json -o restored-python

# Refresh reconstruction metadata for an equivalent organization.
python -m pyfold rebind authoring --against python-src -o refreshed.map.json
```

Directory `fold` emits matching `.fold` files plus `project.map.json`. Reorganize
code into explicit blocks when useful, without converting the other files. An
individual `.fold` file containing module blocks uses the same `unfold` command
and writes a directory containing its modules. A plain individual file still
writes one Python output file. Pass a directory when resolving contributions from
multiple files: the compiler doesn't silently scan outside the supplied input.

`check python-src` without a map verifies a fresh deterministic round trip, just as
`check original.py` does. Authoring-pair checks require a map; `--against` adds the
independent original. Old `project ...` command spellings and headers remain
compatibility aliases; they aren't required to use modules.

## Checks and file handling

The result includes `module_set_matches_map`, `original_file_set_matches`, and each
module's `pair_consistent`, `original_ast_matches`, and `exact_reconstruction`.
Missing, extra or renamed modules fail the set checks. A removed or reordered
statement fails the corresponding original-AST check. An empty ordinary file
represents an empty Python module; an explicit-only file creates just its declared
modules. `rebind` requires the same module path set and ASTs as the independent
original and never changes that original.

Only `.py` / `.fold` inputs are collected. Non-Python assets are not copied. `.git`,
`.venv`, `venv`, and `__pycache__` are ignored. Symlink inputs are rejected. Outputs
must be new/empty and disjoint from inputs to avoid silently retaining stale files.
Paths must be relative POSIX `.py` paths; traversal and case/parent-file collisions
fail. Validation precedes writes, but filesystem errors can leave partial output;
retry with a fresh directory.

## Example

[`examples/project/views`](examples/project/views) groups functions from two modules
in `entities.fold` and their setup in `wiring.fold`, with a package module as well.
The tests also cover mixed implicit/explicit files and blocks alongside ordinary
code. Run:

```sh
python -m pyfold check examples/project/views --map examples/project/project.map.json --against examples/project/python --json
```

No input program is executed during translation or checking. Existing map behavior
is unchanged; this feature is about source organization and resolution.
