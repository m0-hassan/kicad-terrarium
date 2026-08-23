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
        repoint.py       # repoint_text (anchored str.replace)
        verify.py        # registered_libraries, external_libraries
```

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
  as a global library wins; vendoring + registering needs no lib_id
  rewrites. `repoint` exists only for renames.
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
- `scan` counts **instances**; `vendor` keeps **unique definitions**.
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

Done: `pluck`/`list`/config (forward-vendoring, browsing, JSON config) and
`size` (value→package rules for R/C; refuses inductors). Next, in order:

- **interactive picker** over `list`→`pluck` (transient fuzzy-select at the
  decision point only — never a persistent TUI; every picker must keep a
  `--flag` equivalent so scripts and CI never depend on the UI).
- **footprint vendoring** (`fp-lib-table` is the same format; `resolve.py`
  already resolves it) — plus copying `.pretty` and 3D models, and rewriting
  model paths to `${KIPRJMOD}` (audit already flags non-portable ones).
- **orphan recovery**: search paths for a library containing a missing symbol.
