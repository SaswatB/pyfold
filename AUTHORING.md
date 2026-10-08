# Re-express a Python program with PyFold

Use this workflow for a human or LLM editing representations. This is a repository
guide, not an automatically installed personal skill.

## Objective

Express intent clearly while preserving deterministic expansion to the original
Python AST and exact reconstruction through the sidecar. Prefer familiar idioms,
explicit relationships and readable grouping. A longer representation can be better.
Do not optimize character counts at the expense of clarity.

## Workflow

1. Read the repo's README for the supported syntax and semantics. Work against a
   fixed original Python file or revision; never edit the oracle to make checks pass.
2. Run `python -m pyfold fold original.py -o program.fold` for a baseline. Preserve
   the original map before trying changes.
3. Edit a small region of the `.fold` view. Use braced or expression-bodied
   functions, `val` when statically valid, conditionals, interpolation, optional
   parenthesized comprehension clauses and layout choices. Preserve actual binding
   names, evaluation order and Python scope. Identical behavior alone is insufficient
   if the new expansion differs structurally.
4. Run:

   ```sh
   python -m pyfold check program.fold --map program.fold.map.json --against original.py --json
   ```

5. Retain the change only when `ok`, `pair_consistent`, `original_ast_matches`, and
   `exact_reconstruction` are all true. Interpret `null` as not checked, not success.
   A nonzero exit or malformed JSON is a failed gate. Do not weaken validation.
6. If needed, run `rebind program.fold --against original.py -o new.map.json` and
   repeat the independent check. Let the compiler generate redundant metadata;
   don't hand-edit cached source, hashes or recipes to manufacture success.
7. Review the resulting view for readability. Report what intent became clearer,
   what remains in Python escape blocks, and which checks passed. No token/character
   reduction is required. Do not execute unknown input as part of this workflow.

## Boundaries

A `val` can replace a one-write `var`; it cannot silently rename a binding or
eliminate an evaluation. An expression body can replace `{ return expression }`.
A Kotlin conditional can replace the corresponding Python conditional expression.
An `if` statement cannot generally be replaced by a conditional expression under
this AST contract. Loop rewrites, method-chain abstractions, or `retry` syntax need
new compiler rules and tests before they are usable.

If the current grammar cannot express the desired view, retain the existing view
or its explicit Python block. Propose the missing construct separately; never put
executable meaning in sidecar metadata. A future installed skill can wrap this same
workflow, but the checker is the source of truth for correctness.
