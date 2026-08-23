from pathlib import Path

from kicad_terrarium.core.config import Config, dump_config, parse_config


def test_parse_empty_yields_defaults():
    cfg = parse_config("")
    assert cfg == Config(curated_library=None, project_roots=[])


def test_parse_expands_user_paths():
    cfg = parse_config('{"curated_library": "~/lib/mo.kicad_sym", "project_roots": ["~/ee"]}')
    assert cfg.curated_library == Path.home() / "lib/mo.kicad_sym"
    assert cfg.project_roots == [Path.home() / "ee"]


def test_dump_then_parse_round_trips():
    cfg = Config(curated_library=Path("/abs/mo.kicad_sym"), project_roots=[Path("/abs/ee")])
    assert parse_config(dump_config(cfg)) == cfg


def test_dump_omits_unset_fields():
    assert dump_config(Config()) == "{}\n"
