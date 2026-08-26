import json
from pathlib import Path

from typer.testing import CliRunner

from kicad_terrarium import __version__
from kicad_terrarium.cli import app
from kicad_terrarium.core.config import Config
from kicad_terrarium.core.verify import verify_project

runner = CliRunner()


def _project(
    directory: Path,
    *,
    library: str = "Local",
    symbol: str = "A",
    value: str = "Widget",
    footprint: str = "",
    extra_symbol: bool = False,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    root = directory / "board.kicad_sch"
    root.write_text(
        f'''(kicad_sch
  (lib_symbols (symbol "{library}:{symbol}" (pin (number "1"))))
  (symbol (lib_id "{library}:{symbol}")
    (property "Reference" "U1") (property "Value" "{value}")
    (property "Footprint" "{footprint}")))'''
    )
    (directory / "board.kicad_pro").write_text("{}")
    local = directory / "library"
    local.mkdir()
    extra = ' (symbol "Unused")' if extra_symbol else ""
    (local / f"{library}.kicad_sym").write_text(
        f'(kicad_symbol_lib (version 20251024) (symbol "{symbol}"){extra})'
    )
    (directory / "sym-lib-table").write_text(
        f'(sym_lib_table (lib (name "{library}")(type "KiCad")'
        f'(uri "${{KIPRJMOD}}/library/{library}.kicad_sym")))'
    )
    return root


def test_version_is_a_stable_top_level_option():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"kicad-terrarium {__version__}"


def test_bad_project_error_has_no_traceback(tmp_path):
    result = runner.invoke(app, ["verify", str(tmp_path / "missing.kicad_sch")])
    assert result.exit_code == 2
    assert "not a .kicad_sch" in result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_scan_and_verify_describe_a_source_complete_project(tmp_path):
    root = _project(tmp_path / "project")
    scan = runner.invoke(app, ["scan", str(root), "--precise"])
    assert scan.exit_code == 0
    assert "Local" in scan.stdout
    assert "A" in scan.stdout
    assert "1 symbol placement" in scan.stdout

    verify = runner.invoke(app, ["verify", str(root)])
    assert verify.exit_code == 0
    assert "source-complete" in verify.stdout


def test_verify_reports_missing_definition_not_just_registration(tmp_path):
    root = _project(tmp_path / "project")
    (root.parent / "library/Local.kicad_sym").write_text(
        '(kicad_symbol_lib (version 20251024) (symbol "Wrong"))'
    )
    result = runner.invoke(app, ["verify", str(root)])
    assert result.exit_code == 1
    assert "missing symbol definitions" in result.stdout


def test_verify_accepts_an_empty_project_without_a_library_table(tmp_path):
    root = tmp_path / "empty.kicad_sch"
    root.write_text("(kicad_sch)")
    result = runner.invoke(app, ["verify", str(root)])
    assert result.exit_code == 0
    assert "source-complete" in result.stdout


def test_verify_rejects_a_malformed_symbol_id(tmp_path):
    root = tmp_path / "broken.kicad_sch"
    root.write_text('(kicad_sch (symbol (lib_id "not-qualified")))')
    result = runner.invoke(app, ["verify", str(root)])
    assert result.exit_code == 1
    assert "invalid symbol ID" in result.stdout


def test_verify_rejects_a_project_table_symlinked_outside(tmp_path):
    root = _project(tmp_path / "project")
    table = root.parent / "sym-lib-table"
    external = tmp_path / "external-table"
    table.replace(external)
    table.symlink_to(external)

    result = runner.invoke(app, ["verify", str(root)])

    assert result.exit_code == 1
    assert "table resolves outside" in result.stdout


def test_verify_rejects_machine_specific_variables_even_when_they_resolve(tmp_path, monkeypatch):
    root = _project(tmp_path / "project")
    monkeypatch.setenv("MY_PROJECT", str(root.parent))
    (root.parent / "sym-lib-table").write_text(
        '(sym_lib_table (lib (name "Local")(type "KiCad")'
        '(uri "${MY_PROJECT}/library/Local.kicad_sym")))'
    )

    result = runner.invoke(app, ["verify", str(root)])

    assert result.exit_code == 1
    assert "non-portable URI" in result.stdout


def test_audit_reports_unassigned_footprints(tmp_path):
    root = _project(tmp_path / "project")
    result = runner.invoke(app, ["audit", str(root), "--precise"])
    assert result.exit_code == 1
    assert "unassigned footprint" in result.stdout
    assert "has no footprint" in result.stdout


def test_audit_rejects_path_like_footprint_ids_before_filesystem_lookup(tmp_path):
    root = _project(tmp_path / "project", footprint="Parts:../../private")
    result = runner.invoke(app, ["audit", str(root), "--precise"])
    assert result.exit_code == 1
    assert "malformed footprint ID" in result.stdout


def test_list_reads_nested_vault_libraries(tmp_path):
    vault = tmp_path / "vault/sensors"
    vault.mkdir(parents=True)
    (vault / "environmental.kicad_sym").write_text(
        '(kicad_symbol_lib (version 20251024) (symbol "SHT41"))'
    )
    result = runner.invoke(app, ["list", str(tmp_path / "vault")])
    assert result.exit_code == 0
    assert "sensors / environmental" in result.stdout
    assert "SHT41" in result.stdout


def test_list_treats_an_empty_project_catalog_as_a_valid_result(monkeypatch):
    monkeypatch.setattr(
        "kicad_terrarium.commands.common.load_config",
        lambda: Config(),
    )
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "no projects found" in result.stdout


def test_pluck_and_sprout_execute_complete_transfer_plans(tmp_path, monkeypatch):
    project = tmp_path / "project"
    root = _project(project)
    file_vault = tmp_path / "Vault.kicad_sym"
    file_vault.write_text('(kicad_symbol_lib (version 20251024) (symbol "NewPart"))')
    monkeypatch.setattr(
        "kicad_terrarium.commands.common.load_config",
        lambda: Config(curated_library=file_vault),
    )
    pluck = runner.invoke(app, ["pluck", "NewPart", "--into", str(root)])
    assert pluck.exit_code == 0
    assert (project / "library/terrarium/Vault.kicad_sym").is_file()
    project_table = (project / "sym-lib-table").read_text()
    assert '(name "Terrarium__Vault")' in project_table
    assert "(hidden)" not in project_table

    folder_vault = tmp_path / "folder-vault"
    folder_vault.mkdir()
    monkeypatch.setattr(
        "kicad_terrarium.commands.common.load_config",
        lambda: Config(curated_library=folder_vault),
    )
    sprout = runner.invoke(
        app,
        ["sprout", "A", "--from", str(root), "--library", "parts/board"],
    )
    assert sprout.exit_code == 0
    assert (folder_vault / "parts/board.kicad_sym").is_file()


def test_fit_uses_a_named_passive_footprint_policy(tmp_path, monkeypatch):
    root = _project(tmp_path / "project", library="Device", symbol="R", value="10k")
    monkeypatch.setattr(
        "kicad_terrarium.commands.common.load_config",
        lambda: Config(),
    )
    fit = runner.invoke(app, ["fit", str(root), "--profile", "hand-solder"])
    assert fit.exit_code == 0
    assert "Resistor_SMD:R_0603_1608Metric" in root.read_text()


def test_fit_leaves_polarized_capacitors_for_explicit_selection(tmp_path, monkeypatch):
    root = _project(
        tmp_path / "project",
        library="Device",
        symbol="C_Polarized",
        value="100uF",
    )
    monkeypatch.setattr(
        "kicad_terrarium.commands.common.load_config",
        lambda: Config(),
    )
    result = runner.invoke(app, ["fit", str(root)])
    assert result.exit_code == 0
    assert "0 empty footprints assigned" in result.stdout
    assert "U1" in result.stdout
    assert "polarized capacitor" in result.stdout


def test_seal_preserves_user_owned_local_libraries_and_is_idempotent(tmp_path):
    root = _project(tmp_path / "project", extra_symbol=True)
    first = runner.invoke(app, ["seal", str(root)])
    second = runner.invoke(app, ["seal", str(root)])
    assert first.exit_code == second.exit_code == 0
    assert verify_project(root).ok
    assert "Unused" in (root.parent / "library/Local.kicad_sym").read_text()
    assert "unchanged" in second.stdout


def test_noninteractive_init_can_create_a_folder_vault(tmp_path, monkeypatch):
    config_path = tmp_path / "config/config.json"
    monkeypatch.setattr("kicad_terrarium.commands.setup.CONFIG_PATH", config_path)
    monkeypatch.setattr(
        "kicad_terrarium.commands.common.load_config",
        lambda: Config(),
    )
    vault = tmp_path / "vault"
    projects = tmp_path / "projects"
    result = runner.invoke(
        app,
        ["init", "--vault", str(vault), "--projects", str(projects)],
    )
    assert result.exit_code == 0
    assert vault.is_dir()
    assert json.loads(config_path.read_text())["vault"] == str(vault)


def test_init_dry_run_describes_folder_without_creating_it(tmp_path, monkeypatch):
    config_path = tmp_path / "config/config.json"
    monkeypatch.setattr("kicad_terrarium.commands.setup.CONFIG_PATH", config_path)
    monkeypatch.setattr(
        "kicad_terrarium.commands.common.load_config",
        lambda: Config(),
    )
    vault = tmp_path / "vault"
    result = runner.invoke(
        app,
        ["init", "--vault", str(vault), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "create vault folder" in result.stdout
    assert "write Terrarium configuration" in result.stdout
    assert not vault.exists()
    assert not config_path.exists()


def test_help_exposes_only_the_focused_command_surface():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "audit",
        "browse",
        "fit",
        "init",
        "list",
        "pluck",
        "scan",
        "seal",
        "sprout",
        "verify",
    ):
        assert command in result.stdout
    assert "prune" not in result.stdout
    assert "graft" not in result.stdout
