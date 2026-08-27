"""Complete, preflighted plans for every mutating Terrarium workflow."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from kicad_terrarium.core.discover import (
    placed_symbols,
    reassign_footprints,
    used_symbols,
)
from kicad_terrarium.core.extract import (
    assemble_library,
    extends_closure,
    merge_symbols,
    pluck_symbols,
)
from kicad_terrarium.core.io import OperationPlan, read_utf8
from kicad_terrarium.core.library import LibrarySource, SymbolSource, source_blocks, source_version
from kicad_terrarium.core.managed import (
    TERRARIUM_LIBRARY_DIRECTORY,
    TERRARIUM_LIBRARY_PREFIX,
    is_terrarium_managed,
    managed_description,
    terrarium_library_nickname,
)
from kicad_terrarium.core.models import SymbolId
from kicad_terrarium.core.physical import FootprintSealLibraryResult, extend_seal_plan
from kicad_terrarium.core.project import project_lib_ids, project_schematics
from kicad_terrarium.core.repoint import repoint_libraries
from kicad_terrarium.core.resolve import (
    direct_library_registration,
    resolve_global_library_details,
    resolve_library_details,
)
from kicad_terrarium.core.sizing import (
    INDUCTOR_SYMBOLS,
    POLARIZED_CAPACITOR_SYMBOLS,
    Rules,
    footprint_for,
)
from kicad_terrarium.core.tables import (
    portable_project_uri,
    remove_from_sym_lib_table,
    upsert_sym_lib_uris,
    validate_library_nickname,
)


class WorkflowError(ValueError):
    """A complete operation cannot be planned without risking bad output."""


@dataclass
class TransferResult:
    destination: Path
    parents: list[str]
    plan: OperationPlan


@dataclass
class SealLibraryResult:
    nickname: str
    used: int
    kept: int
    changed: bool
    sources: tuple[str, ...] = ()


@dataclass
class SealResult:
    plan: OperationPlan
    libraries: list[SealLibraryResult] = field(default_factory=list)
    footprint_libraries: list[FootprintSealLibraryResult] = field(default_factory=list)
    model_files: int = 0
    changed_model_files: int = 0


@dataclass
class _SealGroup:
    nickname: str
    destination: Path
    wanted: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    candidates: list[Path] = field(default_factory=list)
    hidden: bool = True
    description: str = ""


@dataclass
class FitResult:
    plan: OperationPlan
    applied: list[tuple[str, str]]
    skipped_inductors: set[str]
    skipped_polarized_capacitors: set[str]


def _validate_root(root: Path) -> Path:
    resolved = root.resolve()
    if not resolved.is_file() or resolved.suffix != ".kicad_sch":
        raise WorkflowError(f"not a root .kicad_sch file: {root}")
    return resolved


def _validate_project_ids(values: list[str]) -> None:
    for value in values:
        try:
            symbol_id = SymbolId.parse(value)
            validate_library_nickname(symbol_id.library)
        except ValueError as error:
            raise WorkflowError(str(error)) from error


def _project_plan(root: Path) -> OperationPlan:
    return OperationPlan(root.parent, protected_projects=(root,))


def _project_uri(project_dir: Path, path: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(project_dir):
        raise WorkflowError(f"project library is outside the project: {path}")
    return f"${{KIPRJMOD}}/{resolved.relative_to(project_dir).as_posix()}"


def plan_pluck(
    source: SymbolSource,
    root: Path,
) -> TransferResult:
    """Plan an unambiguous symbol transfer into a self-contained project."""
    root = _validate_root(root)
    project_dir = root.parent
    nickname = terrarium_library_nickname(
        source.library.nickname,
        source.library.group,
    )
    destination = project_dir / TERRARIUM_LIBRARY_DIRECTORY
    destination = destination.joinpath(
        *source.library.group,
        f"{source.library.nickname}.kicad_sym",
    )
    registration = direct_library_registration(project_dir, nickname, table_name="sym-lib-table")
    registered_path = registration[1] if registration is not None else None
    if registration is not None and (
        not is_terrarium_managed(registration[0]) or registered_path != destination.resolve()
    ):
        raise WorkflowError(
            f"reserved destination nickname {nickname!r} is not a Terrarium workbench library"
        )
    if (
        registered_path is not None
        and registered_path.is_relative_to(project_dir)
        and registered_path != destination.resolve()
    ):
        raise WorkflowError(
            f"{nickname!r} already points at a different project-local library: {registered_path}"
        )
    if registration is None:
        collision = resolve_library_details(project_dir).libraries.get(nickname)
        if collision is not None and collision.path.resolve() != destination.resolve():
            raise WorkflowError(f"reserved destination nickname {nickname!r} already exists")

    blocks = source_blocks(source.library)
    additions, missing = pluck_symbols(
        assemble_library(list(blocks), blocks, read_utf8(source.library.files[0])),
        {source.symbol},
    )
    if missing:
        raise WorkflowError(f"source is missing symbol definitions or parents: {sorted(missing)}")
    existing = read_utf8(destination) if destination.is_file() else None
    output, _ = merge_symbols(existing, additions, source_version(source.library))

    table = project_dir / "sym-lib-table"
    table_text = read_utf8(table) if table.is_file() else None
    new_table = upsert_sym_lib_uris(
        table_text,
        {nickname: _project_uri(project_dir, destination)},
        descriptions={nickname: managed_description("workbench", [source.library.selector])},
    )
    plan = _project_plan(root)
    plan.write(destination, output, f"add {source.symbol} to {nickname}")
    plan.write(table, new_table, f"register {nickname}")
    return TransferResult(
        destination,
        sorted(set(additions) - {source.symbol}),
        plan,
    )


def _safe_vault_destination(vault: Path, library: str | None, fallback: str) -> tuple[Path, str]:
    if vault.is_file() and vault.suffix != ".kicad_sym":
        raise WorkflowError(f"file vault must end in .kicad_sym: {vault}")
    if vault.is_file() or (not vault.exists() and vault.suffix == ".kicad_sym"):
        nickname = validate_library_nickname(vault.stem)
        if library is not None and library != nickname:
            raise WorkflowError(
                f"file vault has one library named {nickname!r}; --library cannot change it"
            )
        return vault, nickname
    parts = Path(library or fallback).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise WorkflowError("vault sub-library path is invalid")
    for part in parts:
        validate_library_nickname(part)
    nickname = parts[-1]
    return vault.joinpath(*parts[:-1], f"{nickname}.kicad_sym"), nickname


def plan_sprout(
    source: SymbolSource,
    vault: Path,
    *,
    library: str | None = None,
) -> TransferResult:
    """Plan a symbol transfer into a file vault or nested library folder."""
    destination, nickname = _safe_vault_destination(vault, library, source.library.nickname)
    blocks = source_blocks(source.library)
    synthetic = assemble_library(list(blocks), blocks, read_utf8(source.library.files[0]))
    additions, missing = pluck_symbols(synthetic, {source.symbol})
    if missing:
        raise WorkflowError(f"source is missing symbol definitions or parents: {sorted(missing)}")
    existing = read_utf8(destination) if destination.is_file() else None
    output, _ = merge_symbols(existing, additions, source_version(source.library))
    boundary = vault if vault.is_dir() else vault.parent
    plan = OperationPlan(boundary)
    plan.write(destination, output, f"sprout {source.symbol} into {nickname}")
    return TransferResult(
        destination,
        sorted(set(additions) - {source.symbol}),
        plan,
    )


def _resolved_source(path: Path, nickname: str) -> LibrarySource:
    files = tuple(sorted(path.rglob("*.kicad_sym"))) if path.is_dir() else (path,)
    return LibrarySource(nickname, files, unpacked=path.is_dir())


def plan_seal(root: Path) -> SealResult:
    """Vendor external sources under unique nicknames without hiding globals."""
    root = _validate_root(root)
    project_dir = root.parent
    all_ids = project_lib_ids(root, allow_external=False)
    _validate_project_ids(all_ids)
    used = sorted({lib_id.partition(":")[0] for lib_id in all_ids if ":" in lib_id})
    project_table = project_dir / "sym-lib-table"
    if used and project_table.is_file() and not project_table.resolve().is_relative_to(project_dir):
        raise WorkflowError("project sym-lib-table resolves outside the project")

    visible = resolve_library_details(project_dir)
    global_visible = resolve_global_library_details(project_dir)
    plan = _project_plan(root)
    results: list[SealLibraryResult] = []
    groups: dict[str, _SealGroup] = {}
    rewritten: dict[str, str] = {}
    remove_registrations: set[str] = set()
    delete_legacy_paths: set[Path] = set()
    registrations: dict[str, str] = {}
    hidden_names: set[str] = set()
    descriptions: dict[str, str] = {}

    table_text = read_utf8(project_table) if project_table.is_file() else None

    def add_candidate(group: _SealGroup, path: Path | None) -> None:
        if path is not None and path not in group.candidates:
            group.candidates.append(path)

    for source_nickname in used:
        validate_library_nickname(source_nickname)
        wanted = used_symbols(all_ids, source_nickname)
        visible_source = visible.libraries.get(source_nickname)
        current_path = visible_source.path.resolve() if visible_source else None
        direct_registration = direct_library_registration(
            project_dir, source_nickname, table_name="sym-lib-table"
        )
        source_entry = (
            direct_registration[0]
            if direct_registration is not None
            else (visible_source.entry if visible_source is not None else None)
        )
        managed_local = (
            current_path is not None
            and current_path.is_relative_to(project_dir)
            and is_terrarium_managed(source_entry)
        )
        direct_external_source = (
            direct_registration is not None
            and direct_registration[0].library_type.casefold() == "kicad"
            and current_path is not None
            and not current_path.is_relative_to(project_dir)
        )
        already_namespaced = managed_local and source_nickname.startswith(TERRARIUM_LIBRARY_PREFIX)

        # A user-owned project-local library is already a valid part of the
        # terrarium. Preserve its nickname, contents, and organization.
        if (
            current_path is not None
            and current_path.is_relative_to(project_dir)
            and not managed_local
        ):
            if (
                direct_registration is not None
                and direct_registration[0].library_type.casefold() != "kicad"
            ):
                raise WorkflowError(
                    f"{source_nickname}: direct project nickname is already used by "
                    f"a {direct_registration[0].library_type!r} entry"
                )
            blocks = source_blocks(_resolved_source(current_path, source_nickname))
            _ordered, missing = extends_closure(wanted, blocks)
            if missing:
                raise WorkflowError(
                    f"{source_nickname}: project-local library is missing "
                    f"{', '.join(sorted(missing))}"
                )
            needs_direct_registration = (
                direct_registration is None
                or direct_registration[0].library_type.casefold() != "kicad"
                or direct_registration[1] != current_path
                or not portable_project_uri(direct_registration[0].uri)
            )
            if needs_direct_registration:
                registrations[source_nickname] = _project_uri(project_dir, current_path)
                descriptions[source_nickname] = (
                    source_entry.description
                    if source_entry is not None and source_entry.description
                    else "Project-local library; portable registration maintained "
                    "by kicad-terrarium"
                )
                if source_entry is not None and source_entry.hidden:
                    hidden_names.add(source_nickname)
            results.append(
                SealLibraryResult(
                    source_nickname,
                    len(wanted),
                    len(blocks),
                    needs_direct_registration,
                    (source_nickname,),
                )
            )
            continue

        final_nickname = (
            source_nickname if already_namespaced else terrarium_library_nickname(source_nickname)
        )
        if final_nickname != source_nickname:
            rewritten[source_nickname] = final_nickname

        target_registration = direct_library_registration(
            project_dir, final_nickname, table_name="sym-lib-table"
        )
        target_entry = target_registration[0] if target_registration is not None else None
        target_path = target_registration[1] if target_registration is not None else None
        if target_registration is not None:
            target_entry, target_path = target_registration
            if (
                not is_terrarium_managed(target_entry)
                or target_entry.library_type.casefold() != "kicad"
                or target_path is None
                or not target_path.is_relative_to(project_dir)
                or target_path.is_dir()
                or target_path.suffix != ".kicad_sym"
            ):
                raise WorkflowError(
                    f"{final_nickname}: reserved Terrarium nickname is already used by "
                    "a non-managed library"
                )
            destination = target_path
        elif already_namespaced and current_path is not None:
            destination = current_path
            target_entry = source_entry
        else:
            destination = project_dir / TERRARIUM_LIBRARY_DIRECTORY / f"{source_nickname}.kicad_sym"
            collision = visible.libraries.get(final_nickname)
            if collision is not None:
                raise WorkflowError(
                    f"{final_nickname}: reserved Terrarium nickname already exists; "
                    "rename that library before sealing"
                )
            if destination.exists():
                raise WorkflowError(
                    f"{final_nickname}: refusing to adopt unregistered destination {destination}"
                )

        if destination.suffix != ".kicad_sym":
            raise WorkflowError(
                f"{final_nickname}: managed Terrarium output must be a packed .kicad_sym file"
            )

        group = groups.get(final_nickname)
        if group is None:
            source_stays_searchable = (
                (visible_source is not None and visible_source.entry.scope != "project")
                or source_nickname in global_visible.libraries
                or (
                    direct_registration is not None
                    and not managed_local
                    and not direct_external_source
                )
            )
            group = _SealGroup(
                final_nickname,
                destination,
                hidden=(
                    target_entry.hidden if target_entry is not None else source_stays_searchable
                ),
                description=(
                    target_entry.description
                    if target_entry is not None and is_terrarium_managed(target_entry)
                    else ""
                ),
            )
            groups[final_nickname] = group
            add_candidate(group, target_path if target_path and target_path.exists() else None)
        elif group.destination != destination:
            raise WorkflowError(
                f"{final_nickname}: sources resolve to conflicting project destinations"
            )

        group.wanted.update(wanted)
        group.sources.add(source_nickname)
        add_candidate(group, current_path)

        if managed_local and not already_namespaced:
            remove_registrations.add(source_nickname)
            legacy = project_dir / "library" / f"{source_nickname}.kicad_sym"
            if (
                direct_registration is not None
                and not legacy.is_symlink()
                and legacy.is_file()
                and legacy.resolve() == current_path
                and not any(
                    nickname != source_nickname and library.path.resolve() == current_path
                    for nickname, library in visible.libraries.items()
                )
            ):
                delete_legacy_paths.add(current_path)
        elif direct_external_source:
            # Once the used definitions are local, retaining a machine-specific
            # project row would make the handoff noisy or broken elsewhere.
            remove_registrations.add(source_nickname)

    for group in groups.values():
        combined: dict[str, str] = {}
        version_source: Path | None = None
        for candidate in group.candidates:
            source = _resolved_source(candidate, group.nickname)
            if version_source is None and source.files:
                version_source = source.files[0]
            for name, block in source_blocks(source).items():
                combined.setdefault(name, block)
        ordered, missing = extends_closure(group.wanted, combined)
        if missing:
            origins = ", ".join(sorted(group.sources))
            raise WorkflowError(
                f"{origins}: cannot seal missing definition(s): {', '.join(sorted(missing))}"
            )
        if version_source is None:
            raise WorkflowError(
                f"{', '.join(sorted(group.sources))}: no resolvable symbol-library source"
            )
        output = assemble_library(ordered, combined, read_utf8(version_source))
        before = group.destination.read_bytes() if group.destination.is_file() else None
        plan.write(group.destination, output, f"seal {group.nickname}")
        registrations[group.nickname] = _project_uri(project_dir, group.destination)
        descriptions[group.nickname] = group.description or managed_description(
            "sealed", group.sources
        )
        if group.hidden:
            hidden_names.add(group.nickname)
        results.append(
            SealLibraryResult(
                group.nickname,
                len(group.wanted),
                len(ordered),
                before != output.encode("utf-8")
                or any(rewritten.get(source) == group.nickname for source in group.sources),
                tuple(sorted(group.sources)),
            )
        )

    sheet_outputs: dict[Path, str] = {}
    for sheet in project_schematics(root, allow_external=False):
        output, _counts = repoint_libraries(read_utf8(sheet), rewritten)
        sheet_outputs[sheet] = output

    if remove_registrations or registrations:
        updated = table_text
        if updated is not None and remove_registrations:
            updated = remove_from_sym_lib_table(updated, sorted(remove_registrations))
        updated = upsert_sym_lib_uris(
            updated,
            registrations,
            hidden_names=hidden_names,
            descriptions=descriptions,
        )
        plan.write(project_table, updated, "activate namespaced Terrarium libraries")

    for legacy_path in sorted(delete_legacy_paths):
        plan.delete(legacy_path, "retire migrated Terrarium shadow")

    physical = extend_seal_plan(root, plan, sheet_outputs)
    for sheet, output in physical.sheets.items():
        plan.write(sheet, output, "point project at namespaced Terrarium sources")

    return SealResult(
        plan,
        results,
        physical.libraries,
        physical.model_files,
        physical.changed_model_files,
    )


def plan_fit(root: Path, rules: Rules) -> FitResult:
    root = _validate_root(root)
    plan = _project_plan(root)
    applied: list[tuple[str, str]] = []
    inductors: set[str] = set()
    polarized_capacitors: set[str] = set()
    for sheet in project_schematics(root, allow_external=False):
        text = read_utf8(sheet)
        placements = placed_symbols(text)
        eligible = frozenset(
            (item.reference, str(item.symbol_id))
            for item in placements
            if item.on_board and not item.dnp
        )

        def decide(
            reference: str,
            lib_id: str,
            value: str,
            current: str,
            eligible_symbols: frozenset[tuple[str, str]] = eligible,
        ) -> str | None:
            if current or (reference, lib_id) not in eligible_symbols:
                return None
            return footprint_for(lib_id, value, rules)

        output, changed = reassign_footprints(text, decide)
        unique_changed = sorted(set(changed))
        if unique_changed:
            plan.write(sheet, output, f"apply fit profile {rules.name}")
            applied.extend(unique_changed)
        inductors.update(
            item.reference
            for item in placements
            if item.on_board
            and not item.dnp
            and not item.footprint
            and item.symbol_id.name in INDUCTOR_SYMBOLS
        )
        polarized_capacitors.update(
            item.reference
            for item in placements
            if item.on_board
            and not item.dnp
            and not item.footprint
            and item.symbol_id.name in POLARIZED_CAPACITOR_SYMBOLS
        )
    return FitResult(plan, applied, inductors, polarized_capacitors)


def footprint_summary(applied: list[tuple[str, str]]) -> Counter[str]:
    return Counter(footprint for _reference, footprint in applied)
