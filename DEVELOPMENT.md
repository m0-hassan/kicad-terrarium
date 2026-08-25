# kicad-terrarium — development notes

A Python CLI that makes KiCad schematic projects self-contained. See
README.md for the philosophy; the one-line version: **mechanics belong to
the tool, judgment belongs to the engineer**, and vendored data is copied
byte-for-byte, never round-tripped through a structural parser.

## Quality gates (all must pass before commit)

```bash
pip install -e ".[dev]"   # install with dev extras (pytest, ruff, mypy)
ruff check src tests
ruff format src tests
mypy src
pytest
```

- **ruff** replaces flake8 + black + isort. B008 is suppressed for
  `typer.Argument`/`typer.Option` via `extend-immutable-calls` — intentional.
- `.pre-commit-config.yaml` runs ruff on commit; `pre-commit install` once.
- `build/`, `demo/`, `*.egg-info/`, caches are gitignored. `build/` was once
  committed by accident — never again.

## Architecture

```
src/kicad_terrarium/
    cli.py               # Typer app — thin I/O wrappers only, NO logic here
    core/
        discover.py      # find_lib_ids, sheet_files, library_counts,
                         #   used_symbols, symbol_instances
        project.py       # project_schematics, project_lib_ids (graph walk)
        extract.py       # byte-exact symbol vendoring: block scanner,
                         #   extends closure, library assembly
        resolve.py       # sym/fp-lib-table resolution, path variables,
                         #   KiCad 10 (type "Table") indirection
        tables.py        # sym-lib-table emission + merge
        audit.py         # pad_names, cache_symbol_pins, missing_pads,
                         #   foreign_model_paths
        sizing.py        # value parsers + value→package Rules (fit command)
        config.py        # JSON config: curated library, project roots, sizing
        browse.py        # pure menu state machine (Browser/Screen/Item)
        repoint.py       # repoint_text (anchored str.replace) — the `graft` command
        verify.py        # registered_libraries, external_libraries
```

**Command vs module names.** User-facing command names are chosen for the
audience (EEs): `seal` (= the vendoring op in `extract.py`), `fit` (=
`sizing.py`), `graft` (= `repoint.py`). Internal function names keep the
operation term (`vendor_library`, `repoint_text`) since they describe *what*
the code does. Don't "fix" the mismatch — it's deliberate.

**Core rule:** `core/` functions are pure (data in → data out). Where a file
must be read (`project.py`), the reader is an injected
`Callable[[Path], str]` defaulting to `Path.read_text`, so tests fake the
filesystem with a dict. No fixtures, no tmp dirs except where tables need
real paths (`test_resolve.py`).

## Hard-won constraints (do not relearn these)

- **kiutils must never write KiCad 10 files.** Round-tripping a v20251024
  `.kicad_sym` drops every `(hide yes)` flag and writes `(show_name)` bare
  (= visible), making all symbol properties show in the editor. Vendoring
  copies blocks verbatim; the s-expr scanner in `extract.py` skips quoted
  strings so parentheses in descriptions can't desync it.
- **`extends` closure is mandatory.** Stock symbols inherit
  (OPA2197xD→NCS2325D…); a vendored lib without parents parses but cannot
  be drawn.
- **Shadowing beats repointing.** A project-table entry with the same name
  as a global library wins; sealing + registering needs no lib_id rewrites.
  This is why `seal` uses the *shadow* strategy (many local libs, original
  names) rather than *consolidate* (one project-named lib, all refs rewritten):
  shadow is non-destructive, idempotent (clean git diffs), collision-free, and
  keeps provenance. Consolidate was considered and rejected — its only win is
  aesthetic. `graft` (`repoint_text`) exists only for deliberate renames.
- **KiCad 10 global tables nest**: `(type "Table")` entries point at the
  stock table; resolution follows one level. Table spacing differs between
  KiCad 9 (`(name "x")(type`) and 10 (`(name "x") (type`) — the entry regex
  tolerates both.
- `sym-lib-table` has **no file extension**. Heredocs writing it must quote
  the delimiter or the shell eats `${KIPRJMOD}`.
- KiCad's official libraries ship real footprint bugs (TLV1872DGSR default
  SOIC-8 for a 10-pin part; TMUX6119 default SC-70-6 for an 8-pin part) —
  which is why `audit`'s pin/pad check exists and why "matches the stock
  default" is not proof of correctness.
- `scan` counts **instances**; `seal` keeps **unique definitions**.
  Multi-unit symbols yield one instance block per placed unit — dedupe by
  reference when reporting per-component.
- Old-format (v5) footprint files use unquoted pad names; `audit.pad_names`
  handles both.

## Verification beyond pytest

`kicad-cli` (ships inside the KiCad app) is the authority on whether output
parses: `kicad-cli sym export svg -o /tmp/x lib.kicad_sym` for libraries,
`kicad-cli sch erc` for schematics. Acceptance corpus: any real multi-library
project — vendor a *copy*, then `verify` must pass and every vendored lib
must survive `sym export svg`. Never run write commands against a live
project while KiCad has it open (lock files: `~<name>.kicad_sch.lck`).

## Roadmap

Done: `pluck`/`list`/config, `fit` (R/C value→package), `browse` (curses menu
over pluck; logic in the tested `core.browse` state machine), plus ergonomics
(`kt` alias, cwd-defaulting, compressed output, `scan --precise`). Next:

- **`init` command**: first-run prompt for `curated_library` and
  `project_roots`. Offer to create an empty curated library; do NOT default it
  to KiCad's global library (that's stock parts, not curated) and do NOT
  auto-guess project_roots (KiCad version-dir churn makes guesses wrong).
- **`pluck --from a-schematic`**: also read a `.kicad_sch`'s embedded
  `lib_symbols` cache as a source (recover a symbol whose library was lost).
- **`prune`**: trim every project-local library down to exactly the symbols
  the schematic references. Keeps projects minimal regardless of how much was
  plucked while exploring; a read-the-refs-and-filter op, terrarium-shaped.
- **footprint sealing** (`fp-lib-table` is the same format; `resolve.py`
  already resolves it) — copy `.pretty` + 3D models, rewrite model paths to
  `${KIPRJMOD}` (audit already flags non-portable ones).
- **orphan recovery**: search paths for a library containing a missing symbol.

Default strategy is *shadow* (many local libs, original names, refs untouched),
not *consolidate* (one project-named lib, refs rewritten). The full reasoning —
and what both terms mean — is in `docs/shadow-vs-consolidate.md`. Consolidate is
not rejected outright, but if ever built it's an explicit archival-export mode,
never the default.

Note: the curses render/input loop in `cli._run_browser` is the one piece not
covered by pytest (needs a real TTY). Its logic lives in `core.browse` (tested);
keep the loop a thin view. Verify UI changes by running `browse` in a terminal.
