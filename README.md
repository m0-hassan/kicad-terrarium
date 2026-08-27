# kicad-terrarium

**Custom symbols in; self-contained projects out.**

kicad-terrarium is a fast, local-first KiCad library workflow. It lets you find
and add a custom symbol in a few keystrokes instead of fighting KiCad's library
GUIs, then seal and audit the project so collaborators receive the same editable
symbol sources, footprint sources, and custom 3D assets you used.

The name is the product philosophy: a finished project should be a terrarium —
self-contained, inspectable, and alive without depending on one engineer's
machine.

> Current status: **0.2 beta.** Symbol, footprint, and custom-model sealing is
> implemented and deliberately conservative. The remaining beta work is broader
> real-project and macOS/Linux validation before a stable 1.0 claim.

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
kt seal                   # pin sources under collision-free local nicknames
kt verify                 # prove the used definitions are really present
kt audit                  # expose remaining physical handoff risks
```

Before a professional handoff, preview the seal, apply it, and run both checks:

```bash
kt seal --dry-run
kt seal
kt verify
kt audit
```

Then copy, archive, or commit the complete project folder with the ordinary tool
you already trust for handoffs. Terrarium keeps project mutation focused; it
does not duplicate general-purpose backup or copy tools.

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
- archival handoffs where external library drift is unacceptable.

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
| `audit` | Expose physical handoff risks in assignments, footprints, pins/pads, sheets, and models |
| `seal` | Finalize used symbol/footprint sources and custom models inside the project |
| `verify` | Prove local registrations, containment, definitions, footprints, and models |

Every direct write command supports `--dry-run`. The interactive browser applies
the selected `pluck` or `sprout` action immediately. Global terminal options go
before the command:

```bash
kt --color never audit
kt --theme light browse
kt --version
```

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

A plucked source such as `sensors/environmental` is always registered under the
project nickname `Terrarium__sensors__environmental`. This deterministic mapping
avoids masking a global library with the same name while keeping nested source
identities distinct.

To sprout into a nested vault library:

```bash
kt sprout MySensor --library sensors/environmental
```

The project side of `browse` indexes project-local source libraries. Run
`seal` first when an older project still resolves all of its sources globally.

## What `seal` guarantees

`seal` reads every reachable schematic and the matching board, resolves KiCad's
project and global symbol/footprint tables, follows nested table entries, and
expands standard and user-defined KiCad path variables. It copies each used
symbol definition plus its transitive `extends` parents and each used footprint
source file.

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

Footprints use the same collision-free rule. For example,
`Resistor_SMD:R_0603_1608Metric` becomes
`Terrarium__Resistor_SMD:R_0603_1608Metric`, backed by a pruned project library
under `library/terrarium/footprints/`. Terrarium updates both schematic
Footprint properties and matching board library links, while the complete global
`Resistor_SMD` catalog remains searchable.

Non-stock 3D files outside the project are copied under
`library/terrarium/models/` and their exact model URI tokens become portable
`${KIPRJMOD}` paths. Existing project-contained and `kicad-embed://` models stay
in place. Standard `${KICAD*_3DMODEL_DIR}` and `${KISYS3DMOD}` references remain
normal KiCad installation dependencies; mirroring the complete official model
catalog would add substantial redundant bulk without removing a personal-machine
dependency.

`verify` does not stop at “the nickname appears in a library table.” It checks:

- the entry is enabled, unique, and a supported KiCad source;
- its URI is project-relative rather than machine-specific;
- its path resolves inside the project and exists;
- every used symbol definition is present;
- every required inheritance parent is present;
- unpacked symbol libraries contain no conflicting definitions;
- every used footprint has a project-contained `.kicad_mod` source;
- schematic assignments and board links resolve through portable project entries;
- every non-stock model is embedded or exists at a contained `${KIPRJMOD}` path.

`verify` proves source containment. `audit` asks a different question: whether
the physical design is coherent. It checks missing assignments, footprint
availability and provenance, pin/pad agreement, model paths, and sheet
reachability. If any original symbol, footprint, or custom-model source is gone,
`seal` fails before writing rather than presenting embedded display/board caches
as provenance-equivalent editable sources.

Audit errors return a failing exit status. Advisory findings such as an orphaned
alternate sheet remain visible warnings but do not fail automation by themselves.

### Why the namespace is worth having

KiCad maps one nickname to one underlying library and gives project entries
precedence over globals. A pruned project library named `Connector` would hide
every global connector that was not copied. Namespacing avoids that false
choice: current-design sources are portable and pinned, while the complete
installed catalog remains available for continued design work.

Terrarium creates at most one managed symbol library and one managed `.pretty`
directory per logical source, never one library per part or invocation. It copies
only used definitions rather than mirroring complete KiCad libraries. The vault
and global catalogs remain reusable sources; project copies are deliberate pinned
dependencies.

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
- checks known KiCad lock files for every project asset it will change;
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

Supported platforms are macOS and Linux.

Install the current beta directly from its tagged GitHub release:

```bash
pipx install "git+https://github.com/m0-hassan/kicad-terrarium.git@v0.2.0"
```

For development, install from a checkout:

```bash
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
- no mirroring of complete official KiCad libraries or standard 3D-model catalogs;
- no promise that `audit` can replace KiCad ERC, DRC, or engineering review.

## License

MIT
