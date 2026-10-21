"""Private inputs (config.yaml, location overrides) live outside the package."""

from pathlib import Path

import pytest

from gps_journey.config import InputsDirError, inputs_dir


def test_env_var_overrides_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("GPS_INPUTS_DIR", str(tmp_path))
    assert inputs_dir() == tmp_path


def test_default_is_inputs_under_the_current_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("GPS_INPUTS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert inputs_dir() == tmp_path / "inputs"


def test_blank_env_var_counts_as_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("GPS_INPUTS_DIR", "  ")
    monkeypatch.chdir(tmp_path)
    assert inputs_dir() == tmp_path / "inputs"


def test_missing_dir_errors_and_names_the_variable_and_path(monkeypatch, tmp_path):
    missing = tmp_path / "nope"
    monkeypatch.setenv("GPS_INPUTS_DIR", str(missing))
    with pytest.raises(InputsDirError) as excinfo:
        inputs_dir()
    assert "GPS_INPUTS_DIR" in str(excinfo.value)
    assert str(missing) in str(excinfo.value)


def test_a_file_instead_of_a_dir_errors(monkeypatch, tmp_path):
    a_file = tmp_path / "config.yaml"
    a_file.write_text("log_level: INFO\n")
    monkeypatch.setenv("GPS_INPUTS_DIR", str(a_file))
    with pytest.raises(InputsDirError, match="not a directory"):
        inputs_dir()


def test_error_is_a_value_error():
    assert issubclass(InputsDirError, ValueError)


def test_returns_a_path(monkeypatch, tmp_path):
    monkeypatch.setenv("GPS_INPUTS_DIR", str(tmp_path))
    assert isinstance(inputs_dir(), Path)
