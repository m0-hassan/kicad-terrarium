# Developing kicad-terrarium

Everything a new contributor (or a fresh AI agent with no prior context) needs
to pick this project up. For *what the tool does and why*, read `README.md`
first; for the central design decision, read `docs/shadow-vs-consolidate.md`.
This file is the *how it's built* companion — it doesn't repeat those.

One-line ethos: **mechanics belong to the tool, judgment belongs to the
engineer.** The tool copies, registers, and checks; it never chooses parts.
Corollary that shapes the whole codebase: **library data is copied byte-for-byte,
never round-tripped through a structural parser** (see the kiutils landmine
below).

## Current state (v1.0)

Feature-complete and green: 67 tests, `ruff`/`mypy` clean. Ten commands, all
with `--dry-run` + `.bak` where they write, and cwd-defaulting (run bare from
inside a project). `kt` is a short alias for `kicad-terrarium`.

| command | one line |
|---|---|
| `init` | interactive first-run config (vault + project roots) |
| `scan` | count symbols per library; `--precise` lists exact names |
| `seal` | copy used symbols into `./library`, register them (the headline op) |
| `verify` | exit 1 unless every used library is registered locally |
| `fit` | assign footprints to unassigned R/C by value; `--precise` per-part |
| `audit` | read-only lint (pin/pad, unassigned, orphans, model paths) |
| `list` | browse projects / a library's symbols |
| `pluck` | copy one symbol (+ parents) down into a project, before placing it |
| `sprout` | copy one symbol up into the vault, to reuse later |
| `browse` | curses arrow-key menu over pluck/sprout (with a swaying plant 🌱) |
| `graft` | advanced: rewrite a library name across references (rare) |

Nothing is pushed to a remote yet. Config lives at
`~/.config/kicad-terrarium/config.json`.

## Working on it

```bash
pip install -e ".[dev]"    # dev extras: pytest, ruff, mypy
ruff check src tests && ruff format src tests && mypy src && pytest
```

All four must pass before every commit (`.pre-commit-config.yaml` runs ruff
automatically; `pre-commit install` once). Notes:

- `ruff` replaces flake8 + black + isort. B008 is suppressed for
  `typer.Argument`/`typer.Option` (they're *meant* to be called in defaults).
- Gitignored: `.venv/`, `build/`, `demo/`, `*.egg-info/`, caches. `build/` was
  once committed by accident — keep it out.
- **`kicad-cli`** (inside the KiCad app) is the real authority on whether output
  is valid: `kicad-cli sym export svg -o /tmp/x lib.kicad_sym` for a library,
  `kicad-cli sch erc <root>` for schematics. Use it to accept changes, not just
  pytest.
- **Never run write commands on a live project** while KiCad has it open (lock
  files: `~<name>.kicad_sch.lck`). Test writes on a *copy*.

## Architecture

`core/` is pure (data in → data out); `cli.py` is a thin I/O shell with no
logic. Where a file must be read (`project.py`), the reader is an injected
`Callable[[Path], str]` defaulting to `Path.read_text`, so tests fake the
filesystem with a dict — that's why the suite needs almost no fixtures.

```
src/kicad_terrarium/
  cli.py            Typer app: all I/O, one command per operation
  core/
    discover.py     find_lib_ids, symbol_instances, reassign_footprints, counts
    project.py      project_schematics, project_lib_ids (sub-sheet graph walk)
    extract.py      byte-exact symbol copy: block scanner, extends closure, merge
    resolve.py      sym/fp-lib-table resolution, KiCad path vars, table nesting
    tables.py       sym-lib-table emission + merge
    verify.py       registered vs. used libraries
    audit.py        pad names, cache pin sets, pin/pad diff, foreign model paths
    sizing.py       value parsers + value→package Rules
    config.py       JSON config load/parse/dump
    browse.py       pure menu state machine (Browser / Screen / Item)
    repoint.py      reference-name rewrite
```

**Command names ≠ module names, on purpose.** User-facing names suit the EE
audience — `seal` (the vendoring op in `extract.py`), `fit` (`sizing.py`),
`graft` (`repoint.py`). Internal functions keep the operation term
(`vendor_library`, `repoint_text`) because they describe what the code does.
Don't "reconcile" them.

## Hard-won constraints (do not relearn these the hard way)

Each cost real debugging on real boards; they're the reason the code looks the
way it does.

- **kiutils must never *write* a KiCad 10 file.** Round-tripping a v20251024
  `.kicad_sym` silently drops every `(hide yes)` property flag (writes bare
  `(show_name)`), so every symbol property becomes visible in the editor. This
  is why sealing copies symbol blocks *verbatim*. The s-expression scanner in
  `extract.py` tracks paren depth and skips quoted strings, so parentheses
  inside a description can't desync it, and block boundaries never depend on
  indentation (hand-edited libraries put `)` and the next `(symbol` on one line).
  kiutils is fine for *reading*.
- **`extends` closure is mandatory.** Stock symbols inherit (e.g. OPA2197xD
  extends NCS2325D); a sealed library missing the parent parses but cannot be
  drawn. `extract.extends_closure` pulls parents in, parents-first.
- **Shadowing, not repointing.** A project-table entry outranks a same-named
  global one, so sealing under original names needs zero reference rewrites.
  This is the whole basis of the *shadow* strategy — full reasoning and the
  shadow-vs-consolidate comparison is in `docs/shadow-vs-consolidate.md`.
  `graft`/`repoint_text` exists only for deliberate renames.
- **KiCad 10 lib-tables nest.** A global entry with `(type "Table")` points at
  the stock table; `resolve.py` follows one level of that. Entry spacing differs
  between KiCad 9 `(name "x")(type` and 10 `(name "x") (type` — the regex
  tolerates both. Path vars: `${KIPRJMOD}`, `${KICADn_SYMBOL_DIR}`,
  `${KICADn_FOOTPRINT_DIR}`.
- **`sym-lib-table` has no file extension.** A heredoc writing it must quote the
  delimiter or the shell expands `${KIPRJMOD}`.
- **KiCad's own libraries ship footprint bugs** — TLV1872DGSR defaults to SOIC-8
  for a 10-pin part; TMUX6119 to SC-70-6 for an 8-pin part. That's why `audit`'s
  pin/pad-count check exists: "matches the stock default" is not proof of
  correctness.
- **`scan` counts instances; `seal` keeps unique definitions.** Multi-unit
  symbols emit one instance block per placed unit — dedupe by reference when
  reporting per-component.
- Old (v5) footprint files use unquoted pad names; `audit.pad_names` reads both.
- The curses loop in `cli._run_browser` is the only code not covered by pytest
  (needs a real TTY). Keep it a thin view; its logic lives in the tested
  `core.browse`. Verify UI changes by running `browse` in a terminal (or a
  bounded pty).

## Roadmap

In rough priority order:

- **`prune`** — trim each project-local library to exactly the symbols the
  schematic references. Keeps a project minimal no matter how much was plucked
  while exploring; the answer to pluck "bloat." A read-refs-then-filter op.
- **footprint sealing** — the other half of portability. `fp-lib-table` is the
  same format `resolve.py` already handles; add copying `.pretty` + 3D models
  and rewriting model paths to `${KIPRJMOD}` (`audit` already flags the
  non-portable ones).
- **`pluck --from a-schematic`** — read a symbol out of a `.kicad_sch`'s embedded
  `lib_symbols` cache, for recovering a symbol whose library was lost (the cache
  names symbols `Lib:Name`, so the prefix must be stripped to make a real
  library symbol). Niche recovery, not the everyday path.
- **orphan recovery** — search a path for a library that contains a missing
  symbol.
- polish: the `browse` menu supports arbitrary trees, so "Sizing rules" / "Config"
  screens could be added; paging for very long symbol lists.

`pluck`/`sprout` are the two directions of the same op (project ⇄ vault
library), sharing `_find_symbol_source` + `extract.pluck_symbols`/`merge_symbols`.
`graft` (reference rename) is deliberately kept but niche — with shadow settled,
its only real use is fixing/unifying a badly-named library.

**Test corpus.** The real boards used for acceptance (not committed): `PID`,
`REFLECTOMETER`, `AL-MAWJA`. Pattern: copy one, run the command, then `verify`
must pass and every produced library must survive `kicad-cli sym export svg`.
`~/terrarium-tutorial/` has a scripted, resettable REFLECTOMETER sandbox and a
`TUTORIAL.md` walkthrough of every command.
