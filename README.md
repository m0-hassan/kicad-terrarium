# kicad-terrarium

A terrarium is a sealed glass world: everything the ecosystem needs, carried
inside, alive on any shelf you put it on. **kicad-terrarium makes a KiCad
project like that** — every symbol the design uses is vendored into the
project and verified, so it opens complete on any machine, in five years,
with no global libraries and no memory of your setup.

The tool draws one line and keeps it: **mechanics belong to the tool,
judgment belongs to the engineer.** It counts, copies, registers, and checks;
it never chooses your parts or guesses your intent. Everything irreversible
is preceded by `--dry-run` and a `.bak`; everything checkable exits nonzero
so CI can watch it.

## Commands

Most commands default to the project in the current directory, so from inside
a project you can just run `kt seal`, `kt verify`, `kt audit`. (`kt` is a
short alias for `kicad-terrarium`.)

| Command | What it does |
|---------|-------------|
| `scan [root]` | Count symbols per library (`--precise` lists exact names) |
| `seal [root]` | Copy every used symbol into `./library/`, register it, one command |
| `audit [root]` | Read-only lint: the mechanical gaps that bite during layout |
| `verify [root]` | Exit 1 unless every used library is registered project-locally |
| `list [target]` | Browse configured projects, or the symbols in a library or project |
| `pluck <symbol>` | Copy a symbol (and inherited parents) into a project, before you place it |
| `browse` | Interactive menu over `list`/`pluck`: arrow-key through libraries and projects |
| `fit [root]` | Assign footprints to unassigned resistors and capacitors by value |
| `graft [root] --old X --new Y` | Rewrite lib references (advanced; only for renaming) |

### `seal`

```
$ kt seal
Device: 7 used -> 7 symbols
  ✓ wrote library/Device.kicad_sym
MCU_ST_STM32G4: 1 used -> 2 symbols (+1 inherited parents)
  ✓ wrote library/MCU_ST_STM32G4.kicad_sym
...
✓ registered 8 libraries in sym-lib-table
```

"Sealing" is *vendoring* in software terms — copying your dependencies in so
the project no longer relies on the outside world. It reads the project and
global `sym-lib-table`s (including KiCad 10's nested stock-table indirection)
to find each library's source, copies the used symbols **byte-for-byte** —
plus every `extends` parent, without which a sealed library silently cannot
be drawn — and registers the copies under their original names so they shadow
the globals. No schematic file is touched: shadowing keeps the operation
non-destructive and idempotent (safe to re-run before every commit). Libraries
with no table entry are reported as orphaned, sealable one at a time with
`--source/--library/--output`.

Byte-for-byte matters: structural parsers can silently drop what they don't
understand (we watched one erase every `hide` flag in a KiCad 10 library).
Vendored symbols are verbatim slices of their source.

### `audit`

Checks that need no judgment, only thoroughness — which is exactly what
programs are better at than people:

- symbols with no footprint assigned
- footprint references that resolve to no library or no file
- **symbol pins with no matching pad on the assigned footprint**
- sheet files nothing references
- 3D model paths that won't travel with the project

The pin/pad check alone has caught two wrong default footprints shipped in
KiCad's official libraries (a 10-pin comparator paired with SOIC-8, an 8-pin
switch paired with SC-70-6) — defects that otherwise surface deep into
layout. `audit` is read-only and safe to run while KiCad is open.

### `list` and `pluck`

`seal` works backward from what a project already uses. `pluck` works
forward from intent — it pulls a symbol into a project *before* you place it,
so you never mine an old project or open KiCad just to reuse a part:

```
$ kt list                          # projects, from your config
$ kt list ~/lib/mo-parts.kicad_sym # symbols in a library
$ kt pluck Conn_Coaxial_INVERT     # from your curated library, into the project here
```

`pluck` defaults its source to a personal **curated library** and its
destination to the project in the current directory; both are overridable
(`--from` a library or another project, `--into` a specific project). It
copies the symbol byte-for-byte with any inherited parents, merges it into
the project's library without disturbing what's there, and registers it.
Configure locations in `~/.config/kicad-terrarium/config.json`:

```json
{
  "curated_library": "~/Documents/KiCad/libraries/mo-parts.kicad_sym",
  "project_roots": ["~/Documents/KiCad/projects"]
}
```

Keeping your reusable symbols in one curated library — separate from KiCad's
stock libraries, which are wiped on update — means a part is never trapped
inside a single project again.

`browse` is a full-screen arrow-key menu over the same operations: drill from
your curated library or any project into its symbols and pluck one, without
touching a flag. It's a thin shell — every action it performs is also a
plain command, so scripts and CI never depend on it. (The menu uses stdlib
`curses`; interactive, so Unix terminals only. The rest of the tool is
cross-platform.)

### `fit`

Passive package is partly a function of value: a 10 µF needs more physical
volume than a 100 nF, and an undersized MLCC quietly loses capacitance to
DC-bias derating. `fit` assigns footprints to unassigned resistors and
capacitors from a value table (default: all R at 0603; C at 0603 up to 1 µF,
0805 above), fills only empty footprints, and **leaves inductors alone** —
their package depends on saturation current, which no value reveals. Override
the table under `"sizing"` in the config; always previewable with `--dry-run`.

## Install

```bash
pipx install kicad-terrarium
```

## Develop

```bash
pip install -e ".[dev]"
ruff check src tests && ruff format src tests && mypy src && pytest
```

Pure-core architecture: everything in `core/` is data-in/data-out (file
reads are injected), which is why the test suite needs no fixtures beyond
strings. The CLI is a thin I/O shell. Constraints and architecture notes
live in DEVELOPMENT.md.

## Roadmap

- footprints: seal `.pretty` libraries and 3D models the same way
  (`fp-lib-table` is the same format)
- configurable value→package rules for passives (capacitors and resistors
  only — inductor packages depend on saturation current, which is a
  judgment call, so the tool refuses on principle)
- orphan recovery: search a path for libraries that contain a missing symbol

## Related work

[Component importer for KiCad](https://github.com/robertxdx/component-importer-for-kicad)
solves the opposite, inbound problem — unpacking downloaded SnapEDA/SamacSys/
Ultra Librarian zips into your libraries. A healthy workflow can use both:
it imports parts at design time, terrarium seals and lints the project at
layout time.

## License

MIT
