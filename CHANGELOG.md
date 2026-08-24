# Changelog

## 1.0.0 — 2026-08-23

First public release.

- `vendor` rebuilt on byte-exact symbol extraction: copies symbol blocks
  verbatim (string-aware s-expression scanner), pulls in transitive
  `extends` parents, auto-resolves sources from the project and global
  sym-lib-tables (including KiCad 10's nested stock-table indirection),
  and registers vendored libraries so they shadow the globals — one
  command, no flags, no schematic rewrites.
- New `audit` command: read-only lint for unassigned footprints,
  unresolvable footprint references, symbol-pin/footprint-pad mismatches,
  orphaned sheet files, and non-portable 3D model paths.
- New `pluck` command (with `list` and a JSON config): copy a named symbol,
  plus any inherited parents, from a curated library or another project into
  the current project — forward-vendoring, so a reusable part is never
  trapped inside one project. `list` browses projects and library symbols
  without opening KiCad.
- New `size` command: assign footprints to unassigned resistors and
  capacitors by value (configurable table; 0603/0805 defaults), filling only
  empty footprints and refusing inductors (saturation current is a human
  decision).
- New `browse` command: a full-screen arrow-key menu (stdlib curses) over
  `list`/`pluck` — drill from the curated library or any project into its
  symbols and pluck one. Navigation is a tested pure state machine
  (`core.browse`); the menu carries no logic of its own, so every action
  remains a plain flag-driven command. Unix terminals only.
- kiutils removed: round-tripping KiCad 10 symbol libraries through it
  drops every `(hide yes)` property flag. Reading and writing are now
  text-based throughout.
- `repoint` retained as a rename utility; shadowing makes it unnecessary
  for self-containment.

## 0.1.0 — 2026-08

Initial development version: `scan`, kiutils-based `vendor`, `repoint`,
`verify`.
