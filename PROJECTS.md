# Many-to-many projects

A project consists of any number of `.fold` files plus an optional project map.
Each authoring file starts with `#!pyfold project 1` and contains explicit module
fragments:

```text
#!pyfold project 1
module "app/users.py" part 10 {
    fun find_user(id) = PREFIX + str(id)
}

module "app/orders.py" part 20 {
    fun order_for_user(id) = find_user(id)
}
```

Other authoring files can supply additional fragments for these same modules.
The tuple `(module path, part number)` is the fragment's explicit identity/order.
Part numbers are unique nonnegative integers within each module; gaps are allowed.
They can be repeated across different modules. Duplicate numbers within a module
are an error, even if their contents are identical. Sort order is numeric, so part
2 precedes part 10. Authoring filenames and fragment discovery order have no effect
on generated Python order.

Use arbitrary `.fold` filenames to group related concepts. Moving an entire module
block between authoring files does not require any map changes. Splitting/merging
blocks also works, provided the parts assemble to the same Python AST. The baseline
converter numbers top-level statements 0, 10, 20, ... to leave insertion room.

Each fragment must contain complete top-level statements. Functions and classes
can move between authoring files but cannot yet be split internally across parts.
Module-level imports, globals, decorators and initialization statements remain in
their original Python module, in explicit part order. Relative imports, package
`__init__.py` files, module docstrings and future imports retain Python semantics.
Imports aren't automatically renamed or inferred; invalid future-import placement
is rejected during whole-module compilation. No new cross-module execution order
is introduced: Python's own import/runtime machinery governs that.

## Commands

Convert all `.py` files under a source tree:

```sh
python -m pyfold project fold python-src -o authoring
```

This generates corresponding `.fold` paths with movable fragments, plus
`authoring/project.map.json`. Baseline output is one-to-one by default; the format
supports many-to-many immediately. Non-Python assets are not copied. `.git`, `.venv`,
`venv` and `__pycache__` directories are excluded. Symlink inputs are rejected.

Compile standalone or reconstruct with a map:

```sh
python -m pyfold project unfold authoring -o canonical-python
python -m pyfold project unfold authoring --map authoring/project.map.json -o restored-python
```

Outputs must be new/empty directories disjoint from the input tree. This avoids
silently keeping stale Python modules after a module is removed. Invalid input is
validated before writing. Filesystem write failures can still leave partial output;
use a fresh destination when retrying. Paths must be relative POSIX `.py` paths.
Absolute paths, traversal, duplicate parts and case/parent-file collisions fail.

Check the entire file set and each module against the independent original tree:

```sh
python -m pyfold project check authoring --map authoring/project.map.json --against python-src --json
```

The JSON result includes `module_set_matches_map`, `original_file_set_matches`, and
per-module `pair_consistent`, `original_ast_matches`, and `exact_reconstruction`.
`ok` requires every requested check to pass. Missing, added or renamed Python paths
fail the file-set checks. Removing a fragment while retaining its module is detected
by the module's original-AST check. Without `--against`, consistency does not prove
preservation of an independent original. An empty module needs an explicit empty
module block; omitting it means the module does not exist.

Generate fresh metadata after reorganizing the view:

```sh
python -m pyfold project rebind authoring --against python-src -o refreshed.map.json
```

Rebinding requires the exact same module path set and ASTs as the original. Like
single-file rebinding, it produces whole-module reconstruction recipes. No routing
or execution order lives in the map. For semantic module additions/removals, compile
standalone first and establish an explicitly updated original before rebinding.

## Working example

[`examples/project/views`](examples/project/views) maps three Python files onto two
PyFold files. `entities.fold` holds functions from both `store/users.py` and
`store/orders.py`; `wiring.fold` supplies their globals/imports and the package file.
Thus both substantive Python modules draw from both authoring files.

```sh
python -m pyfold project check examples/project/views --map examples/project/project.map.json --against examples/project/python --json
```

No Python code executes during conversion or checking. Existing single-file v1/v2
commands are unchanged. This release adds project organization and verification;
it does not introduce new map semantics or claim a stronger security boundary.
