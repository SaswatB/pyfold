# Design notes

## Core invariants

The visible program determines executable meaning. Sidecar removal can change
formatting but cannot introduce a different Python AST. A sidecar is not a bag
of code generation overrides: restoration requires AST equivalence.

The current pipeline is Python AST + source slices → concise view + source cache.
The reverse path parses the view → canonical Python → optional matching source
restoration → module validation. The untouched fast path returns exact source
only after validating the sidecar's view/source relationship and checksum.

This is a source-slice prototype, not a lossless concrete syntax tree. Changed
functions are regenerated wholesale. A future CST layer should preserve
unaffected tokens inside a function, rather than only top-level fragments.

## A useful next milestone

1. Give bindings and expression nodes stable identities in a semantic IR.
2. Separate semantic ordering/binding facts from presentation names/layout.
3. Define a restricted non-reflective mode for stronger transformations.
4. Recognize one real verbose pattern, with explicit effect restrictions.
5. Store the original expansion as a reconstruction recipe.
6. Reapply a recipe only when the edited IR still satisfies its preconditions.
7. Compare execution against reference cases that observe ordering, exceptions,
   side effects, aliasing and scope. AST equality alone will no longer suffice.

Start with local naming abstraction before loop rewriting. A temporary can be
displayed as a semantic binding with a short generated name while retaining its
original spelling in the sidecar. This requires scope resolution and rejection
or explicit treatment of locals/frame reflection. Names occurring in strings
must never be blindly renamed. The current prototype deliberately keeps names.

## Losslessness has levels

- Text: unchanged source plus metadata reconstructs exactly.
- AST: source and view compile to the same ordinary Python syntax structure.
- Observable execution: stronger and dependent on reflection/effect contracts.
- Edit intent: cannot be guaranteed by hashing; needs node identity and merge UX.

Only the first two are implemented here. Python AST equality ignores comments,
formatting and locations. It does not prove equivalence for source inspection,
tracing or traceback-sensitive programs. No claims of fully lossless observation
under arbitrary edits are made.

## Ownership and synchronization

Choose one authoritative authoring file. No background bidirectional sync is
implemented. A later editor should use a base revision plus stable IDs to detect
conflicts instead of silently choosing between independent changes. Sidecars
must be diffable, versioned and validated before restoration.

## Grammar scope

Headers use Python tokenization to find outer delimiters, avoiding corruption
from dictionaries, strings, annotations and nested calls. Statements retain
Python grammar. More surface features should move to a real lexer/parser, not
expand into a collection of regular-expression rewrites.
