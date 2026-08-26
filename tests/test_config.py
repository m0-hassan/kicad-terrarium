from pathlib import Path

import pytest

from kicad_terrarium.core.config import Config, ConfigError, dump_config, load_config, parse_config


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


@pytest.mark.parametrize(
    "text, message",
    [
        ("{", "invalid JSON"),
        ("[]", "root"),
        ('{"project_roots":"no"}', "project_roots"),
        ('{"project_roots":[""]}', "blank"),
        ('{"sizing":[]}', "sizing"),
        ('{"fit_profile":""}', "fit_profile"),
        ('{"fit_profile":"magic"}', "hand-solder or custom"),
        ('{"theme":"papyrus"}', "theme"),
        ('{"valut":"typo"}', "unknown configuration"),
        ('{"vault":"a","curated_library":"b"}', "not both"),
    ],
)
def test_invalid_config_has_actionable_errors(text, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(text)


def test_load_absent_config_returns_defaults(tmp_path):
    assert load_config(tmp_path / "missing.json") == Config()


def test_load_rejects_non_utf8_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes(b"\xff")
    with pytest.raises(ConfigError, match="not UTF-8"):
        load_config(path)


def test_nondefault_profile_and_theme_round_trip():
    config = Config(fit_profile="custom", theme="light")
    assert parse_config(dump_config(config)) == config


def test_legacy_sizing_selects_custom_but_explicit_profile_wins():
    legacy = parse_config('{"sizing":{"resistor":"Parts:R"}}')
    assert legacy.fit_profile == "custom"
    explicit = parse_config('{"fit_profile":"hand-solder","sizing":{"resistor":"Parts:R"}}')
    assert explicit.fit_profile == "hand-solder"
    assert parse_config(dump_config(explicit)) == explicit
