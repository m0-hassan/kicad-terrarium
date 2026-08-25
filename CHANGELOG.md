# Changelog

## 1.0.0 — 2026-08

First public release.

- `seal` (the headline command): byte-exact symbol vendoring. Copies symbol
  blocks verbatim (string-aware s-expression scanner), pulls in transitive
  `extends` parents, auto-resolves sources from the project and global
  sym-lib-tables (including KiCad 10's nested stock-table indirection), and
  registers the copies under their original names so they shadow the globals —
  one command, no flags, non-destructive (no schematic rewrites) and
  idempotent (safe before every commit). ("Sealing" is *vendoring* in software
  terms.)
- `audit`: read-only lint for unassigned footprints, unresolvable footprint
  references, symbol-pin/footprint-pad mismatches, orphaned sheet files, and
  non-portable 3D model paths.
- `pluck` / `sprout` (with `list`, `init`, and a JSON config): move a single
  symbol (plus inherited parents) between a project and your vault.
  `pluck` pulls one down into a project before you place it; `sprout` pushes
  one up into the collection so it grows from real reuse. `list` browses
  projects and library symbols; `scan --precise` lists exact symbol names,
  without opening KiCad. `init` is an interactive first-run setup that
  suggests a descriptive vault name (its name propagates into every
  project via shadowing, so a personal handle is discouraged).
- `fit`: assign footprints to unassigned resistors and capacitors by value
  (configurable table; 0603/0805 defaults), filling only empty footprints and
  refusing inductors (saturation current is a human decision). Output is
  summarized by package; `--precise` for the full per-part list.
- `browse`: a full-screen arrow-key menu (stdlib curses) over pluck/sprout,
  with a swaying potted sprout in the corner. A vault symbol plucks straight
  into the project; a project symbol opens a pluck-here / sprout-up choice.
  Navigation is a tested pure state machine (`core.browse`); the menu carries
  no logic of its own, so every action remains a plain flag-driven command.
  Unix terminals only.
- `graft`: advanced/niche reference-rename utility (formerly `repoint`).
  Shadowing makes it unnecessary for self-containment; kept for deliberate
  library renames/merges.
- Ergonomics: `kt` short alias; all project commands default to the project in
  the current directory (run `kt seal` from inside a project, no path needed).
- kiutils removed: round-tripping KiCad 10 symbol libraries through it drops
  every `(hide yes)` property flag. Reading and writing are text-based
  throughout.

## 0.1.0 — 2026-08

Initial development version: `scan`, a kiutils-based early `seal`, `graft`,
`verify`.
