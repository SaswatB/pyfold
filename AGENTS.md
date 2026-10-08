# Product constraints

Treat these as requirements, not optional preferences.

- Keep one composable authoring language and one set of commands. Do not introduce
  user-facing modes, feature toggles, settings, or required headers to enable normal
  language features. File organization and module declarations are not modes.
- Infer behavior from the program and input structure. Module declarations can
  occur in any authoring file and are resolved across all supplied input files.
  Ordinary files must continue to work without opting into a project/module mode.
- Only add a setting when unavoidable for compatibility, such as an explicit
  target Python version. Explain why inference cannot solve the concrete need;
  keep the exception narrow. Do not use this exception for implementation convenience.
- Retain old command spellings as compatibility aliases where practical, but do
  not present those aliases as separate products or workflows in new documentation.
- Optimize authoring for understandable intent, not just minimum length. Multiple
  representations may expand deterministically to the same Python AST.
- Keep original module identity, ordering, bindings and evaluation semantics
  checkable. Do not weaken original-source checks merely to accept a representation.
- Keep an independent original when validating re-expression. Validate file sets
  as well as per-module expansion and exact reconstruction.

# Development

- Run `python -m unittest discover -s tests -v` for parser/compiler changes.
- Add focused tests for representation changes, ambiguity and failed validation.
- Keep README examples executable and describe actual limitations accurately.
- Existing source maps are presentation caches; changes to their logic/semantics
  require a separate, explicit design decision.
