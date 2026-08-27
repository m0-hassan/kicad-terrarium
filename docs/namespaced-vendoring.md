# Why Terrarium namespaces project-contained libraries

This is Terrarium's central KiCad architecture decision.

## The portability and search problem

KiCad identifies a symbol or footprint as `nickname:name` and maps each nickname
to one library in the corresponding table. Project entries take precedence over
global entries; they are not merged.

A pruned project library registered as `Connector` therefore makes the project
portable, but it also hides the complete global `Connector` catalog. That is a
bad trade for both active development and a professional handoff.

Terrarium instead separates the two identities:

```text
Connector:Conn_01x02
    -> Terrarium__Connector:Conn_01x02

global search source:
    Connector -> installed complete KiCad library

project dependency:
    Terrarium__Connector
      -> ${KIPRJMOD}/library/terrarium/Connector.kicad_sym
```

The current design resolves from the project-contained source. The complete
global catalog remains available for adding new parts.

The footprint side is deliberately symmetrical:

```text
Resistor_SMD:R_0603_1608Metric
    -> Terrarium__Resistor_SMD:R_0603_1608Metric

project dependency:
    Terrarium__Resistor_SMD
      -> ${KIPRJMOD}/library/terrarium/footprints/Resistor_SMD.pretty
```

Both the schematic assignment and an existing board's library link are updated.
The complete installed `Resistor_SMD` catalog remains available.

## What is copied

Terrarium creates at most one managed project library for each logical source.
It copies only:

- symbols currently used by reachable project sheets;
- their transitive `(extends ...)` parents;
- symbols explicitly plucked into a visible workbench library.
- footprints referenced by reachable schematics or the matching board;
- non-stock 3D files those footprints or board instances reference.

It never creates a library per symbol and does not mirror an entire installed
catalog. There is at most one managed symbol library and one managed `.pretty`
directory per logical source. Separate per-source libraries preserve
name-collision boundaries and provenance that a consolidated library would lose.

Standard KiCad 3D-model variables remain installation dependencies. Existing
project-contained and embedded models already travel; private external models
are copied to deterministic project paths.

Sealed external dependencies are marked hidden in KiCad's chooser while
remaining loaded. Plucked custom libraries stay visible because they are part
of the daily authoring workflow.

## Vault versus project

The reusable vault and project copy have different jobs:

```text
vault                         project terrarium
authoritative reusable work  pinned, portable dependency copy
```

- `pluck` copies a selected vault definition into `Terrarium__<source>`.
- `sprout` deliberately promotes project work back into the vault.
- `seal` captures every remaining external source used by the design.
- `verify` proves that all currently used source definitions travel.

There is no silent bidirectional synchronization. Local duplication is the
deliberate and bounded cost of reproducibility.

## Atomic reference migration

Namespacing requires source-identifier edits, but they are narrow and
mechanical. Terrarium changes only actual `lib_id` forms and cached-symbol
identifiers. Descriptions, values, properties, and unrelated text are left
untouched.

The following are committed as one operation:

1. namespaced library files;
2. exact schematic identifier rewrites;
3. project table registrations;
4. retirement of recognized legacy Terrarium shadows;
5. pruned footprint directories and portable `fp-lib-table` registrations;
6. schematic Footprint properties, board library links, and model paths;
7. copied non-stock model files.

Every existing file changed or retired receives a unique adjacent backup. A
failure rolls the complete operation back.

User-owned project-local libraries are not renamed. Automatic migration is
limited to entries whose description identifies them as managed or vendored by
kicad-terrarium.

## Alternatives rejected

### Same-nickname shadows

They avoid schematic diffs, but remove all uncopied global symbols from KiCad's
chooser. This directly damages the workflow Terrarium is meant to improve.

### Copy complete upstream libraries

This preserves the catalog as it existed at sealing time, but copies hundreds
of unused definitions, becomes stale, and still hides later global updates.

### Consolidate into one project library

One file looks tidy but collapses provenance and creates a collision policy for
same-named symbols and inheritance parents from different sources.

### Depend on schematic caches alone

Embedded symbols are excellent for rendering and recovery, but are not a
replacement for editable, registered source libraries.

## The resulting promise

Terrarium does not ship the universe of symbols someone might add in the
future. It makes the current design source-complete while preserving normal
access to the user's installed libraries:

> The speed of a personal symbol vault, with the confidence of a
> self-contained professional handoff.
