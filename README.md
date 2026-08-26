# kicad-terrarium

**Custom symbols in; self-contained projects out.**

kicad-terrarium is a fast, local-first KiCad library workflow. It lets you find
and add a custom symbol in a few keystrokes instead of fighting KiCad's library
GUIs, then seal and audit the project so collaborators receive the same editable
symbol sources you used.

The name is the product philosophy: a finished project should be a terrarium —
self-contained, inspectable, and alive without depending on one engineer's
machine.

> Current status: **0.2 beta.** The symbol workflow is usable and deliberately
> conservative. Footprint and 3D-model *auditing* exists; automatic footprint and
> model vendoring does not yet.

## The workflow

Configure a reusable vault once. A vault can be one packed library or a folder
of nested sub-libraries:

```bash
kt init --vault ~/Documents/KiCad/terrarium-vault \
  --projects ~/Documents/electronics
```

Then, from a KiCad project:

```bash
kt browse                 # browse/search visually, then select
kt pluck SHT41            # or pull a known symbol directly from the vault
kt fit --dry-run          # preview an explicit passive-footprint policy
kt audit                  # layout-critical mechanical checks
kt seal                   # pin sources under collision-free local nicknames
kt verify                 # prove the used definitions are really present
```

For a professional handoff without changing your working copy:

```bash
kt seal --snapshot ../my-board-handoff
```

The snapshot is built separately, sealed, deeply verified, and only then moved
into place. The original project is untouched.

## Why this exists

KiCad's library managers are capable but expensive to traverse while a project
is taking shape. The common high-friction moment is small: you already made a
good custom part, you know roughly where it lives, and you want it in the new
project now. `pluck`, `list`, and `browse` turn that into a local search and a
couple of keys.

The second problem appears at handoff. Since KiCad 6, schematics embed resolved
symbol copies, which is excellent for opening and rendering a design. That is
not the same as shipping the editable source libraries and project table needed
to select more symbols, inspect provenance, or maintain the project normally.
Terrarium makes that source layer travel too.

This is useful for:

- engineers who repeatedly reuse custom parts across new projects;
- teams reviewing or extending a design on another workstation;
- client, manufacturing, classroom, or open-source handoffs;
- archival snapshots where external library drift is unacceptable.

It is intentionally not a component downloader, electrical-rule oracle, or
replacement for KiCad.

## Commands

| Command | Purpose |
|---|---|
| `init` | Configure a file/folder vault and project search roots |
| `browse` | Full-screen search/navigation across vault and project symbols |
| `list` | List projects, libraries, or symbols without opening KiCad |
| `pluck` | Copy one symbol and inherited parents into a project |
| `sprout` | Promote one project symbol into the reusable vault |
| `scan` | Show the libraries and exact symbols used by reachable sheets |
| `fit` | Fill empty resistor/non-polar-C footprints using a named policy |
| `audit` | Check assignments, files, pin/pad consistency, sheets, and models |
| `seal` | Finalize all used symbol sources in place or into a snapshot |
| `verify` | Verify local registrations, containment, files, definitions, and parents |
| `prune` | Remove unused definitions using table nicknames, including aliases |
| `graft` | Deliberately rename exact library references across project sheets |

Every mutating command supports `--dry-run`. `--json` is available globally for
automation:

```bash
kt --json scan --precise
kt --json verify
kt --color never audit
kt --version
```

Global options go before the command.

Project traversal visits each reachable schematic file once. Scan/audit counts
are therefore source placements, not expanded counts for a sheet instantiated
multiple times in a hierarchical design.

## Vaults and sub-libraries

All of these are valid vault shapes:

```text
custom_symbols.kicad_sym             one packed library

terrarium-vault/                     a folder of sub-libraries
  passives.kicad_sym
  sensors/
    environmental.kicad_sym
    magnetic.kicad_sym

Device.kicad_symdir/                 one KiCad unpacked library
  R.kicad_sym
  C.kicad_sym
```

An ordinary folder is treated as a hierarchy of logical libraries. A
`.kicad_symdir` is treated as one unpacked logical library. If the same symbol
name exists in several sub-libraries, Terrarium refuses to guess:

```bash
kt pluck SharedPart --from-library sensors/environmental
```

By default, a plucked source such as `sensors/environmental` is registered under
the project nickname `Terrarium__sensors__environmental`. This avoids masking a
global library with the same name while keeping nested source identities
distinct. Use `--as` only when you deliberately want another exact destination
nickname.

To sprout into a nested vault library:

```bash
kt sprout MySensor --library sensors/environmental
```

The project side of `browse` indexes project-local source libraries. Run
`seal` first when an older project still resolves all of its sources globally.

## What `seal` guarantees

`seal` reads every reachable schematic, resolves KiCad's project and global
library tables, follows nested table entries, expands standard and user-defined
KiCad path variables, and copies each used definition plus its transitive
`extends` parents.

External sources receive deterministic project-local identities such as
`Terrarium__Connector` and live under `library/terrarium/`. Terrarium rewrites
only the corresponding schematic source identifiers in the same atomic plan.
The ordinary global `Connector` library therefore remains fully searchable in
KiCad while existing project symbols stay pinned to their local editable
definitions. Generated dependency libraries can remain loaded but hidden from
the symbol chooser; actively plucked workbench libraries remain visible.

A valid user-owned project library already organized inside the project is
preserved without renaming. Older same-nickname libraries explicitly marked as
Terrarium-managed are migrated automatically. Their registrations and exact
schematic references are replaced together, and the retired files plus every
changed schematic/table receive adjacent `.bak`, `.bak.1`, … recovery copies.

`verify` does not stop at “the nickname appears in `sym-lib-table`.” It checks:

- the entry is enabled, unique, and a supported KiCad source;
- its URI is project-relative rather than machine-specific;
- its path resolves inside the project and exists;
- every used symbol definition is present;
- every required inheritance parent is present;
- unpacked directory libraries contain no conflicting definitions.

The narrower claim matters: this verifies **symbol-source completeness**. Until
footprint/model sealing lands, `audit` may still report external physical assets.
If an original symbol source is already gone, `seal` fails rather than silently
presenting the schematic's embedded display cache as provenance-equivalent
source.

### Why the namespace is worth having

KiCad maps one nickname to one underlying library and gives project entries
precedence over globals. A pruned project library named `Connector` would hide
every global connector that was not copied. Namespacing avoids that false
choice: current-design sources are portable and pinned, while the complete
installed catalog remains available for continued design work.

Terrarium creates at most one managed library per logical source, never one
per symbol or invocation. It copies only the used dependency closure rather
than mirroring complete KiCad libraries. The vault remains the reusable source;
the project copy is a deliberate pinned snapshot.

### Migrating an older Terrarium project

Close KiCad, make a normal version-control commit or copy the project folder,
then preview the exact migration:

```bash
kt seal /path/to/board.kicad_sch --dry-run
```

Only entries whose description identifies them as Terrarium-managed are
automatically migrated; deliberate project-local libraries are preserved. Apply
and verify:

```bash
kt seal /path/to/board.kicad_sch
kt verify /path/to/board.kicad_sch
```

The first command keeps adjacent backups of every changed schematic/table and
each retired legacy library. Open the project and confirm both its existing
symbols and a search in a formerly shadowed global library before treating the
migration as accepted.

## Safe mutation model

Terrarium plans the complete operation before writing anything. A plan:

- rejects paths outside its project/vault boundary;
- rejects ambiguous symbols and conflicting same-name definitions;
- refuses external sub-sheet mutation;
- checks KiCad project and symbol-library lock files before writes;
- hashes every destination and detects changes made after planning;
- stages and fsyncs writes beside their destination;
- uses atomic replacement and rolls back a partial commit;
- keeps adjacent, unique `.bak`, `.bak.1`, … recovery copies.

Do not intentionally run a write command while KiCad has the project open.
Terrarium checks known lock names, but no external lock protocol is infallible.

## `fit` is a policy, not an oracle

`fit` only fills empty resistor and generic non-polar capacitor footprints. It
never overwrites an assignment. It leaves inductors alone because package choice
needs saturation-current data, and leaves polarized capacitors alone because
technology and package cannot be inferred safely from capacitance.

The bundled `hand-solder` profile uses 0603 resistors, 0603 generic capacitors
through 1 µF, and 0805 above. That is an assembly-convenience baseline — it does
**not** validate voltage rating, dielectric, DC-bias derating, power, tolerance,
or availability. The selected policy is printed every time.

Custom rules live in the config:

```json
{
  "vault": "~/Documents/KiCad/terrarium-vault",
  "project_roots": ["~/Documents/electronics"],
  "fit_profile": "custom",
  "sizing": {
    "resistor": "Resistor_SMD:R_0805_2012Metric",
    "capacitor": [
      {"max": "100nF", "footprint": "Capacitor_SMD:C_0603_1608Metric"},
      {"max": "4.7uF", "footprint": "Capacitor_SMD:C_0805_2012Metric"},
      {"footprint": "Capacitor_SMD:C_1206_3216Metric"}
    ]
  },
  "theme": "auto"
}
```

Malformed thresholds, duplicate thresholds, missing catch-alls, and malformed
footprint IDs are hard errors rather than silent fallbacks.

## Terminal design

Terrarium uses a restrained botanical identity rather than generic rainbow
status output. Only compact status labels carry semantic color; the useful text
stays neutral. The banner has separate dark- and light-background forest
palettes:

```bash
kt --theme light          # beige, papyrus, or other light terminal background
kt --theme dark
NO_COLOR=1 kt audit       # standard no-color convention
```

The full-screen browser needs `curses` and an interactive input/output terminal.
Search with `/`; all underlying actions remain ordinary scriptable commands.

## Install and develop

Until a public package is published, install from a checkout:

```bash
pipx install .
# or, for development
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Quality gate:

```bash
ruff check src tests
ruff format --check src tests
mypy src
pytest --cov --cov-fail-under=75
python -m build
twine check dist/*
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for the architecture and invariants, and
[the namespaced-vendoring rationale](docs/namespaced-vendoring.md) for the
central KiCad design decision.

## Explicit non-goals for now

- no cloud account, daemon, telemetry, or proprietary catalog;
- no automatic electrical part selection;
- no inductor sizing from value alone;
- no schematic-wide consolidation as the default;
- no database/HTTP/foreign-library extraction masquerading as supported;
- no automatic footprint or 3D-model vendoring until their portability model is
  implemented and tested end to end.

## License

MIT
