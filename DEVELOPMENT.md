# Developing kicad-terrarium

Read [README.md](README.md) first for the product. This document describes the
implementation boundaries that should survive future work.

## Product contract

Terrarium has two equally important jobs:

1. make custom-symbol reuse dramatically faster than KiCad's library GUI path;
2. make professional handoffs source-complete and self-contained across symbols,
   footprints, and custom 3D assets.

The governing principle is: **automate declared mechanics; expose engineering
judgment.** Copying an exact symbol block is mechanics. Applying a named fit
profile is declared policy. Choosing an inductor package or pretending package
size proves electrical suitability is not.

## Architecture

```text
src/kicad_terrarium/
  cli.py                  Typer assembly and global terminal options only
  presentation.py         botanical palette, NO_COLOR, restrained statuses
  commands/
    common.py              output/config/project/error boundaries
    inspect.py             scan, audit, verify
    transfer.py            list, pluck, sprout, seal
    setup.py               init and fit
    browser.py             curses view/search; no transfer logic
  core/
    models.py              precise shared domain records
    sexpr.py               string-aware source-span scanner
    discover.py            placed symbols, sheets, exact footprint edits
    footprints.py          board links and exact model/footprint URI edits
    project.py             bounded sub-sheet graph traversal
    extract.py             verbatim definition copy/inheritance/merge
    library.py             packed, unpacked, and nested-vault discovery
    tables.py              structural table parsing and span edits
    resolve.py             cross-platform KiCad table/path resolution
    verify.py              deep source-completeness proof
    audit.py               footprint/pad/model primitives
    managed.py             shared Terrarium namespaces and provenance
    physical.py            footprint/model half of the seal plan
    sizing.py              validated named R/C assignment policy
    io.py                  atomic plans, backups, locks, rollback
    workflows.py           complete preflighted mutation plans
    browse.py              pure navigation/search state
    repoint.py             targeted library-reference edits
```

Dependency direction is one-way: `cli` → `commands` → `core`. Core modules do
not print, prompt, or depend on Typer/Rich/curses. Commands translate exceptions
and domain results into concise human output.

The command split is by workflow, not one tiny file per verb. Avoid rebuilding a
single CLI wall, but also avoid fragmenting one operation across arbitrary
wrappers.

## KiCad parsing strategy

Do not round-trip project files or symbol libraries through a general object
serializer. An earlier kiutils path dropped KiCad 10 `(hide yes)` and
`(show_name no)` details. Terrarium instead uses a small string-aware
S-expression scanner that records exact spans.

Rules:

- reads must not depend on indentation or line endings;
- edits replace only the token/form spans they own;
- unknown and future forms remain byte-for-byte untouched;
- quoted parentheses and escaped quotes must not affect depth;
- packed symbol definitions are copied verbatim;
- assembled wrapper text may be synthesized, but copied blocks may not;
- malformed input is a hard, user-facing error — never “best effort” output.

`core.sexpr` is intentionally not a full AST or serializer. Keep it small.

## Symbol-library invariants

- A symbol ID is exactly `nickname:name`; colons and path separators are not
  valid Terrarium-generated nicknames.
- Every selected symbol includes the transitive closure of `(extends ...)`
  parents, parents first.
- A same-name, byte-different definition is a conflict, not a duplicate to skip.
- Ordinary vault directories contain sub-libraries. A `.kicad_symdir` denotes
  one unpacked logical library. KiCad itself permits any folder as an unpacked
  source; table-resolved folders are therefore treated as one library.
- Ambiguous symbol search must ask for `--from-library`; discovery order must
  never select a winner silently.
- Pluck destinations are derived from the complete source path; every entry
  point must preserve the same deterministic namespace.

## Sealing semantics

`seal` is in-place project finalization, not a substitute for ERC/DRC and not a
mandatory pre-commit ritual.

Default sealing uses namespaced project-local dependencies:

- map an external `Connector` source to `Terrarium__Connector`;
- write its used definition closure under
  `library/terrarium/Connector.kicad_sym`;
- rewrite only matching `lib_id` and cached-symbol identifiers;
- register the namespaced source with a portable `${KIPRJMOD}` URI;
- keep the original global nickname unshadowed and searchable;
- hide sealed external dependencies from the chooser while keeping them loaded;
- keep actively plucked workbench libraries visible;
- preserve a valid user-owned source that is already inside the project;
- migrate only old project libraries whose table description identifies them
  as Terrarium-managed;
- fail on a reserved-nickname collision or unregistered canonical destination;
- fail the entire plan if any used definition or parent is unresolved.

There is at most one managed output library per logical source. Never create
one file per symbol. Multiple per-source files preserve collision domains and
provenance without copying complete upstream catalogs.

Footprint sealing mirrors those principles:

- map external `Resistor_SMD` to `Terrarium__Resistor_SMD`;
- copy only referenced `.kicad_mod` files into one managed `.pretty` directory;
- rewrite exact schematic Footprint properties and matching board links;
- preserve valid user-owned project-local footprint libraries;
- keep the complete global footprint source unshadowed and searchable;
- copy non-stock external model files to content-stable project paths;
- leave project-contained, embedded, and standard KiCad model paths in place;
- fail the complete plan if an assigned footprint or custom model is unavailable.

The standard KiCad 3D-model catalog is an accepted installation dependency. Do
not mirror it into projects. This is the physical equivalent of depending on
KiCad itself, not on one engineer's private filesystem.

The library write, table edit, reference rewrites, and retirement of recognized
legacy shadows belong to one `OperationPlan`. An in-place migration therefore
creates recovery backups for every changed schematic, table, and retired source
and rolls back the complete set on failure.

KiCad 6+ embeds symbol copies in schematics and footprint geometry in boards.
`verify` deliberately checks the stronger promise that editable symbol and
footprint sources plus non-stock model files also travel. `audit` separately
checks physical coherence such as assignments and pin/pad agreement.

## Mutation protocol

Every write command must build one `OperationPlan` before applying it.

The plan owns:

1. explicit filesystem boundaries;
2. expected SHA-256 state for every destination;
3. known KiCad project and changed-asset lock-file checks;
4. same-directory temporary staging and `fsync`;
5. unique adjacent recovery backups;
6. atomic `os.replace` commits;
7. reverse-order rollback after a partial failure.

Dry-run output is rendered from the same plan that real execution applies. Do
not add direct `Path.write_text`, `unlink`, or one-off `.bak` logic to commands.

Mutating operations traverse sheets with `allow_external=False`. A project may
legally reference an external sheet, but Terrarium must surface that boundary
instead of silently changing another project.

## Resolution behavior

`core.resolve` handles:

- project tables shadowing global tables, including broken project entries;
- an explicit global-only view used to migrate a known shadow without
  pretending normal KiCad resolution falls through it;
- nested `(type "Table")` indirection with cycle detection;
- macOS and Linux/XDG configuration roots (Windows is not currently supported);
- `${KIPRJMOD}` and versioned KiCad symbol/footprint/model/template variables;
- user variables from the newest `kicad_common.json`;
- environment variables and table-relative paths;
- packed files and unpacked folders;
- explicit diagnostics for unresolved variables, missing paths, bad tables, and
  unsupported DB/HTTP/foreign sources.

Do not silently fall back to a global library when a project entry with the same
nickname is dangling. KiCad shadowing makes the dangling entry authoritative;
concealing it gives `seal` and `audit` a false view of the project.

## Fit policy

`hand-solder` is a convenience profile, not a component qualification model.
Every invocation prints its limitations. Custom capacitor rules require:

- parseable positive thresholds;
- unique ascending thresholds;
- exactly one final catch-all;
- non-empty `Library:Footprint` IDs at the CLI boundary.

Only empty, on-board, non-DNP resistors and generic non-polar capacitors are
eligible. Existing footprints are immutable. Inductors and polarized capacitors
remain human decisions.

## Terminal UI

The status system colors only a short semantic word (`done`, `plan`, `warning`,
`error`, `unchanged`). Avoid emoji/checkmark/cross ornament and rainbow output.
`NO_COLOR`, `--color`, and light/dark botanical palettes are part of the public
behavior.

The curses browser remains a thin view over the pure navigation state in
`core/browse.py`; symbol transfer belongs in workflows rather than the UI loop.

## Quality gate

Set up:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Before merging:

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=75
.venv/bin/python -m build
.venv/bin/twine check dist/*
```

Mypy runs in strict mode. CI covers Python 3.10, 3.12, and 3.14 on Linux, adds a
macOS 3.12 gate, and builds the distribution on the newest Linux interpreter.

Tests should prefer real minimal S-expression fixtures over mocked call graphs.
The highest-value regression corpus includes:

- arbitrary valid formatting and escaped strings;
- missing definitions despite present registrations;
- malformed and multiline library tables;
- namespaced external sources coexisting with their complete global libraries;
- migration of recognized legacy shadows with automatic recovery backups;
- preservation of deliberate project-local libraries;
- project aliases whose nickname differs from filename;
- custom KiCad variables and broken shadow entries;
- directory/unpacked vaults and duplicate symbol ambiguity;
- conflicting same-name definitions;
- stale writes, lock files, path escapes, rollback, and unique backups;
- end-to-end command flows;
- browser transfers preserving nested source identity.
- footprint source namespacing across schematic and board references;
- project/global footprint provenance and missing definitions;
- stock, project-contained, embedded, unresolved, and external model paths;
- idempotent custom-model copying and board-only mechanical models.

When available, validate generated libraries with the installed KiCad CLI as an
additional integration authority:

```bash
kicad-cli sym export svg -o /tmp/terrarium-check library/Foo.kicad_sym
kicad-cli sch erc board.kicad_sch
```

Those checks are optional because KiCad is not available on all CI runners; they
do not replace the source-preservation tests.

## Release discipline

- Keep `pyproject.toml` and `kicad_terrarium.__version__` synchronized.
- Update `CHANGELOG.md` for user-visible behavior.
- Build both wheel and sdist and run `twine check`.
- Do not describe a version as released until an artifact or tag actually
  exists.
- Do not commit `build/`, `dist/`, egg-info, caches, demo projects, lock files,
  or user configuration.
