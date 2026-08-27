import shutil
import subprocess
from pathlib import Path

import pytest

from kicad_terrarium.core.verify import verify_project
from kicad_terrarium.core.workflows import plan_seal

FIXTURE = Path(__file__).parent / "fixtures/kicad10"


def _kicad_cli() -> str:
    discovered = shutil.which("kicad-cli")
    macos = Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
    executable = discovered or (str(macos) if macos.is_file() else "")
    if not executable:
        pytest.skip("KiCad CLI is not installed")
    version = subprocess.run(
        [executable, "version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if not version.startswith("10."):
        pytest.skip("the committed acceptance fixture targets KiCad 10")
    return executable


def test_kicad_accepts_a_namespaced_footprint_seal(tmp_path):
    executable = _kicad_cli()
    project = tmp_path / "project"
    source = tmp_path / "external/Fixture.pretty"
    shutil.copytree(FIXTURE / "project", project)
    shutil.copytree(FIXTURE / "source/Fixture.pretty", source)
    (project / "fp-lib-table").write_text(
        f'(fp_lib_table (lib (name "Fixture")(type "KiCad")(uri "{source}")))'
    )
    root = project / "board.kicad_sch"

    first = plan_seal(root)
    first.plan.apply()

    sealed = project / "library/terrarium/footprints/Fixture.pretty"
    assert "Terrarium__Fixture:Widget" in (project / "board.kicad_pcb").read_text()
    assert verify_project(root).ok
    assert plan_seal(root).plan.changes == []

    subprocess.run(
        [executable, "sch", "erc", "-o", str(tmp_path / "erc.rpt"), str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            executable,
            "pcb",
            "drc",
            "-o",
            str(tmp_path / "drc.rpt"),
            str(project / "board.kicad_pcb"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    svg = tmp_path / "svg"
    svg.mkdir()
    subprocess.run(
        [executable, "fp", "export", "svg", "-o", str(svg), str(sealed)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (svg / "Widget.svg").is_file()
