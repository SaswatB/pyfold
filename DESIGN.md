# Design notes

## One program, multiple representations

The deterministic converter selects a baseline; it does not prescribe the only
valid view. Humans and LLMs can select different syntax/layout to clarify intent.
Every supported representation expands through fixed compiler rules.

V2 uses a dedicated lexer and recursive-descent statement parser. Strings, comments,
raw blocks and delimiter nesting are lexical units. Indentation is ignored outside
Python escape blocks. Expressions use token-aware aliases, conditional expressions
and interpolation, then Python's AST parser validates the resulting grammar.
This is a hybrid parser, not a full TypeScript/Kotlin expression grammar.

## Verification

The visible view determines executable meaning. The sidecar contains a source cache
and is validated before restoration. Its absence cannot secretly change the AST.

`check view --map map --against original` separates three claims:

1. The pair reconstructs an AST matching standalone compilation.
2. That AST matches independently retained original Python.
3. Reconstruction reproduces the original source text exactly.

Check 1 alone cannot catch an LLM changing both halves consistently. Checks 2 and 3
must use an independent source. AST equality deliberately rejects many potentially
valid semantic refactors; no heuristic claim of behavioral equivalence is accepted.

When whole-module ASTs match, reconstruction returns the original text after
validation. Otherwise, source fragments are reused by AST shape, consuming duplicate
matches in order. Changed fragments are regenerated. Source inspection, tracebacks,
tracing and comment-based tooling are not generally invariant under regenerated
source. Exact reconstruction restores the original source presentation.

`rebind` accepts a new equivalent view and original Python, rejects AST changes,
and generates a whole-module recipe. It reduces metadata-hand-editing risk at the
cost of fine-grained preservation after later semantic edits. This tradeoff is
explicit and tested. No stable edit identities or conflict merging are claimed.

## Extending the representation vocabulary

The next milestone is a symbol-aware intermediate representation with explicit
ordering and effects. A higher-level construct needs a documented deterministic
expansion and tests for names, order, exceptions, scope and aliasing. If expansion
can retain the original AST, the existing checker can gate it. If it changes the
AST, it needs a separate equivalence contract; do not relabel an AST mismatch as a
pass based on model judgment or a few passing executions.

Source presentation belongs in the map. Semantics belong in the view or an explicit
versioned language/import definition. User-defined macros, retries and arbitrary
expansion recipes are not implemented in this release.

## Synchronization

Choose one authoritative authoring file. Keep an immutable original for checks.
There is no background bidirectional sync. A future editor needs base revisions and
stable identities to merge independent changes. Current sidecars are redundant,
diffable source caches, not compressed formats or cryptographic attestations.
