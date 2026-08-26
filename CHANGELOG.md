# Changelog

## 0.2.0 — 2026-08-26

First release-candidate beta after the repository-wide product and engineering
audit. The earlier in-repository `1.0.0` label was never published or tagged and
overstated the project's readiness; versioning now reflects its real maturity.

### Product direction

- Reframed Terrarium around both halves of its purpose: add custom symbols to a
  new project in a few keystrokes, then ship source-complete, self-contained
  professional handoffs.
- Added file vaults, ordinary directory vaults with nested sub-libraries, and
  KiCad unpacked `.kicad_symdir` discovery.
- Added duplicate-symbol disambiguation by nickname or full nested path with
  `--from-library`, plus sprout targets such as `--library sensors/environmental`.
- Defined `seal` as focused, in-place project finalization; copying and archiving
  remain the responsibility of normal filesystem or version-control tools.
- Replaced pruned same-nickname shadows with namespaced project dependencies
  such as `Terrarium__Connector`, so the complete global KiCad library remains
  searchable while used project symbols resolve from portable local sources.
- Made every `pluck` entry point preserve the complete source identity and map it
  deterministically to a visible `Terrarium__<source>` workbench library.
- Removed the prototype `prune` and `graft` commands: sealing already minimizes
  managed dependencies, while destructive cleanup and arbitrary renaming do not
  belong in the compact core workflow.

### Reliability and correctness

- Replaced indentation-sensitive schematic discovery and regex table parsing
  with a string-aware S-expression source-span scanner.
- Namespaced sealing edits only actual `lib_id` and cached-symbol identifiers;
  matching descriptions and values are untouched.
- Added deep verification of registration uniqueness, project containment,
  source existence, exact used definitions, inheritance parents, and unpacked
  directory conflicts.
- Made broken project-table shadows authoritative rather than silently falling
  back to a global entry.
- Added cross-platform KiCad config locations, semantic version-directory
  ordering, relative table URIs, nested-table cycle handling, and custom path
  variables from `kicad_common.json`.
- Normalized nested or machine-specific registrations for already-local sources
  into direct `${KIPRJMOD}` entries, and made deep verification reject absolute
  paths, user variables, and project-table symlinks that would break on move.
- Added explicit diagnostics for missing paths, unresolved variables, malformed
  tables, and unsupported DB/HTTP/foreign sources.
- Made same-name, different-definition merges hard conflicts.
- Validated library nicknames and nested vault paths to prevent output escape.
- Refused mutating traversal through external sub-sheets.

### Safe writes

- All normal write commands now build one complete operation plan before
  mutation.
- Added filesystem-boundary enforcement, expected-content hashes, KiCad lock
  checks, same-directory staging, `fsync`, atomic replacement, rollback after
  partial failure, and unique adjacent backups.
- Dry-run uses the same plan as real execution.
- Missing definitions abort a seal before any empty library or partial table is
  written.
- Added automatic migration for legacy libraries explicitly identified as
  Terrarium-managed. Library creation, exact reference rewrites, table changes,
  and old-shadow retirement are one rollback-safe operation with adjacent
  backups for every changed or retired file.

### Fit and audit

- Retained `fit` as a central feature, but made its assumptions explicit through
  named policies.
- The `hand-solder` policy describes itself as an assembly baseline, not an
  electrical qualification model.
- Custom sizing rejects malformed/duplicate thresholds, missing catch-alls, and
  malformed footprint IDs instead of silently broadening a rule.
- Fit only touches empty, on-board, non-DNP resistor and generic non-polar
  capacitor placements; it refuses to infer inductor or polarized-capacitor
  packages.
- Audit now understands formatting-independent placed symbols, respects
  on-board/DNP state, reports missing cached pin data, checks only used footprint
  models, verifies `${KIPRJMOD}` model existence, and discovers orphan sheets
  recursively.

### CLI and terminal design

- Split the previous 973-line `cli.py` into cohesive inspect, transfer, setup,
  browser, presentation, and workflow layers.
- Added `--version`, `--color auto|always|never`, `NO_COLOR`, and
  `--theme auto|dark|light`.
- Replaced bright check/cross ornament with restrained semantic status labels.
- Replaced the sunset banner with adaptive botanical gradients for dark and
  light/beige terminal backgrounds.
- Added `/` search to the interactive browser.

### Engineering

- Added precise domain records for IDs, placements, table entries, resolution,
  and diagnostics.
- Enabled strict mypy, Python 3.10 targeting, typed-package metadata, branch
  coverage, a 75% CI floor, distribution builds, and `twine check`.
- Expanded the suite from 74 to 147 tests, including adversarial source formats,
  deep verification, library ambiguity, path escapes, lock/stale-write checks,
  rollback, and nested browser transfers.
- Updated CI to test Python 3.10, 3.12, and 3.14 with pip caching, read-only
  permissions, concurrency cancellation, and packaging validation.

## 0.1.0 — 2026-08

Initial prototype: scan, byte-preserving symbol extraction, shadow-based seal,
pluck/sprout, fit, prune, audit, verify, graft, and a basic curses browser.
