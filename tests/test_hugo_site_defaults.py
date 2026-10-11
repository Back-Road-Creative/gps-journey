"""Hugo site locations have no default pointing at another project.

``HugoConfig`` leaves every site path unset until the user configures it
(process environment variable, ``HUGO__<NAME>`` in a ``.env`` file, or a
``hugo:`` mapping through ``Config.from_yaml``), and ``export-metadata`` falls
back to a directory under the current directory when nothing is configured.
Every existing option and environment variable still overrides.
"""

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gps_journey.cli import app
from gps_journey.config import Config, HugoConfig

runner = CliRunner()

SITE_VARIABLES = {
    "content_path": "HUGO_CONTENT_PATH",
    "image_path": "HUGO_IMAGE_PATH",
    "map_path": "HUGO_MAP_PATH",
    "static_path": "HUGO_STATIC_PATH",
}


# Every process-environment name any settings section reads, including the bare
# section names (a variable named exactly HUGO feeds the nested ``hugo`` field).
_SETTINGS_PREFIXES = ("HUGO_", "GEOCODING_", "MAPS_", "PROCESSING_", "GOOGLE_PHOTOS_")
_SETTINGS_NAMES = ("HUGO", "MAPS", "GEOCODING", "PROCESSING", "GOOGLE_PHOTOS", "LOG_LEVEL")


def _is_settings_variable(name):
    # The settings reader is case-insensitive, so compare upper-cased names.
    upper = name.upper()
    return upper.startswith(_SETTINGS_PREFIXES) or upper in _SETTINGS_NAMES


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """No settings variable from the caller's shell reaches the test."""
    for name in [n for n in os.environ if _is_settings_variable(n)]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("field", sorted(SITE_VARIABLES))
def test_site_paths_default_to_unset(clean_env, field):
    assert getattr(HugoConfig(), field) is None


@pytest.mark.parametrize("field,variable", sorted(SITE_VARIABLES.items()))
def test_environment_variable_still_sets_each_path(clean_env, monkeypatch, field, variable):
    monkeypatch.setenv(variable, "configured/location")
    assert getattr(HugoConfig(), field) == Path("configured/location")


@pytest.mark.parametrize("field", sorted(SITE_VARIABLES))
def test_dotenv_nested_spelling_sets_each_path(clean_env, monkeypatch, field):
    nested = SITE_VARIABLES[field].replace("HUGO_", "HUGO__", 1)
    monkeypatch.delenv(nested, raising=False)
    (clean_env / ".env").write_text(f"{nested}=from/dotenv\n", encoding="utf-8")
    assert getattr(Config().hugo, field) == Path("from/dotenv")


@pytest.mark.parametrize("field", sorted(SITE_VARIABLES))
@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_environment_variable_counts_as_unset(clean_env, monkeypatch, field, blank):
    monkeypatch.setenv(SITE_VARIABLES[field], blank)
    assert getattr(HugoConfig(), field) is None


@pytest.mark.parametrize("field", sorted(SITE_VARIABLES))
def test_blank_dotenv_value_counts_as_unset(clean_env, monkeypatch, field):
    nested = SITE_VARIABLES[field].replace("HUGO_", "HUGO__", 1)
    monkeypatch.delenv(nested, raising=False)
    (clean_env / ".env").write_text(f"{nested}=\n", encoding="utf-8")
    assert getattr(Config().hugo, field) is None


def test_export_metadata_blank_content_path_uses_the_fallback(clean_env, monkeypatch):
    monkeypatch.setenv("HUGO_CONTENT_PATH", "")
    result = runner.invoke(app, ["export-metadata", "missing-trip"])
    assert result.exit_code == 1
    assert str(Path("output") / "journeys") in result.output


def test_yaml_hugo_mapping_sets_the_content_path(clean_env):
    yaml_file = clean_env / "config.yaml"
    yaml_file.write_text("hugo:\n  content_path: from/yaml\n", encoding="utf-8")
    assert Config.from_yaml(yaml_file).hugo.content_path == Path("from/yaml")


def test_archetype_default_is_unchanged(clean_env):
    assert HugoConfig().archetype == "journey"


def test_export_metadata_defaults_to_a_directory_under_the_cwd(clean_env):
    result = runner.invoke(app, ["export-metadata", "missing-trip"])
    assert result.exit_code == 1
    assert "Looked in:" in result.output
    assert str(Path("output") / "journeys") in result.output
    assert ".." not in result.output


def test_export_metadata_uses_the_configured_content_path(clean_env, monkeypatch):
    monkeypatch.setenv("HUGO_CONTENT_PATH", str(Path("configured") / "content"))
    result = runner.invoke(app, ["export-metadata", "missing-trip"])
    assert result.exit_code == 1
    assert str(Path("configured") / "content") in result.output
    assert str(Path("output") / "journeys") not in result.output


def test_export_metadata_hugo_dir_option_overrides_the_config(clean_env, monkeypatch):
    monkeypatch.setenv("HUGO_CONTENT_PATH", str(Path("configured") / "content"))
    result = runner.invoke(
        app, ["export-metadata", "missing-trip", "--hugo-dir", str(Path("explicit") / "dir")]
    )
    assert result.exit_code == 1
    assert str(Path("explicit") / "dir") in result.output
    assert str(Path("configured") / "content") not in result.output


# --- running from a directory whose .env belongs to another tool -----------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="synthetic" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="10.0000" lon="20.0000"><ele>10</ele><time>2031-01-01T10:00:00Z</time></trkpt>
    <trkpt lat="10.0100" lon="20.0100"><ele>12</ele><time>2031-01-01T10:10:00Z</time></trkpt>
    <trkpt lat="10.0200" lon="20.0200"><ele>14</ele><time>2031-01-01T10:20:00Z</time></trkpt>
  </trkseg></trk>
</gpx>
"""


def _run_cli(cwd, *args, extra_env=None):
    """Run the CLI in a fresh interpreter whose cwd holds an unrelated .env.

    The caller's own settings variables are dropped so the result does not depend
    on the shell the suite runs from; ``extra_env`` adds back what a test needs.
    """
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if not _is_settings_variable(k)}
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-c", "from gps_journey.cli import app; app()", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_export_metadata_ignores_an_unrelated_dotenv(tmp_path):
    (tmp_path / ".env").write_text("UNRELATED_TOOL_SETTING=1\n", encoding="utf-8")
    result = _run_cli(tmp_path, "export-metadata", "missing-trip", "--hugo-dir", "explicit")
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Journey not found" in output
    assert "Extra inputs" not in output


def test_export_metadata_default_dir_ignores_an_unrelated_dotenv(tmp_path):
    (tmp_path / ".env").write_text("UNRELATED_TOOL_SETTING=1\n", encoding="utf-8")
    result = _run_cli(tmp_path, "export-metadata", "missing-trip")
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Journey not found" in output
    assert "Extra inputs" not in output


def test_process_output_ignores_an_unrelated_dotenv(tmp_path):
    (tmp_path / ".env").write_text("UNRELATED_TOOL_SETTING=1\n", encoding="utf-8")
    gpx = tmp_path / "track.gpx"
    gpx.write_text(_GPX, encoding="utf-8")
    result = _run_cli(tmp_path, "process", str(gpx), "--output", str(tmp_path / "trip.md"))
    output = result.stdout + result.stderr
    assert "Extra inputs" not in output
    assert result.returncode == 0, output


# Settings input a Hugo command cannot use: a value that fails validation in
# another section, a bare HUGO variable that is not a mapping (for example a path
# to the hugo binary), and a key the Hugo section does not have.
BAD_OTHER_SECTION = [
    {"LOG_LEVEL": "info"},
    {"MAPS_WIDTH": "abc"},
    {"HUGO": "/usr/local/bin/hugo"},
    {"HUGO__UNKNOWN": "1"},
]


def _write_gpx(tmp_path):
    gpx = tmp_path / "track.gpx"
    gpx.write_text(_GPX, encoding="utf-8")
    return gpx


@pytest.mark.parametrize("bad_env", BAD_OTHER_SECTION)
def test_process_static_dir_option_loads_no_settings(tmp_path, bad_env):
    result = _run_cli(
        tmp_path,
        "process",
        str(_write_gpx(tmp_path)),
        "--output",
        str(tmp_path / "trip.md"),
        "--static-dir",
        str(tmp_path / "static"),
        extra_env=bad_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Ignoring unreadable Hugo settings" not in result.stdout + result.stderr


@pytest.mark.parametrize("bad_env", BAD_OTHER_SECTION)
def test_process_without_static_dir_loads_no_settings(tmp_path, bad_env):
    result = _run_cli(
        tmp_path,
        "process",
        str(_write_gpx(tmp_path)),
        "--output",
        str(tmp_path / "trip.md"),
        extra_env=bad_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Ignoring unreadable Hugo settings" not in result.stdout + result.stderr


@pytest.mark.parametrize("bad_env", BAD_OTHER_SECTION)
def test_export_metadata_hugo_dir_option_loads_no_settings(tmp_path, bad_env):
    # An unusable setting must not change the outcome when the option is given.
    result = _run_cli(
        tmp_path, "export-metadata", "missing-trip", "--hugo-dir", "explicit", extra_env=bad_env
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Journey not found" in output
    assert "validation error" not in output
    assert "Ignoring unreadable Hugo settings" not in output


@pytest.mark.parametrize("bad_env", BAD_OTHER_SECTION)
def test_export_metadata_without_option_ignores_unusable_settings(tmp_path, bad_env):
    result = _run_cli(tmp_path, "export-metadata", "missing-trip", extra_env=bad_env)
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Journey not found" in output
    assert "validation error" not in output
    assert "extra_forbidden" not in output
    assert str(Path("output") / "journeys") in output


@pytest.mark.parametrize("bad_env", BAD_OTHER_SECTION)
def test_export_metadata_keeps_the_configured_path_beside_unusable_settings(tmp_path, bad_env):
    result = _run_cli(
        tmp_path,
        "export-metadata",
        "missing-trip",
        extra_env={**bad_env, "HUGO_CONTENT_PATH": "configured_dir"},
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Journey not found" in output
    assert "configured_dir" in output


def test_export_metadata_dotenv_ignores_an_unknown_hugo_key(tmp_path):
    (tmp_path / ".env").write_text(
        "HUGO__VERSION=1\nHUGO__CONTENT_PATH=dotenv_dir\n", encoding="utf-8"
    )
    result = _run_cli(tmp_path, "export-metadata", "missing-trip")
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Journey not found" in output
    assert "dotenv_dir" in output


def test_export_metadata_reads_the_hugo_path_beside_a_bad_other_section(tmp_path):
    result = _run_cli(
        tmp_path,
        "export-metadata",
        "missing-trip",
        extra_env={"LOG_LEVEL": "info", "HUGO_CONTENT_PATH": "configured_dir"},
    )
    assert result.returncode == 1
    assert "configured_dir" in result.stdout + result.stderr


def test_export_metadata_reads_the_dotenv_spelling_beside_a_bad_other_section(tmp_path):
    (tmp_path / ".env").write_text("HUGO__CONTENT_PATH=dotenv_dir\n", encoding="utf-8")
    result = _run_cli(tmp_path, "export-metadata", "missing-trip", extra_env={"LOG_LEVEL": "info"})
    assert result.returncode == 1
    assert "dotenv_dir" in result.stdout + result.stderr


def test_export_metadata_survives_an_unreadable_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("HUGO__CONTENT_PATH=configured\n", encoding="utf-8")
    env_file.chmod(0)
    try:
        result = _run_cli(tmp_path, "export-metadata", "missing-trip")
    finally:
        env_file.chmod(0o600)
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Journey not found" in output
    assert "Permission denied" not in output
