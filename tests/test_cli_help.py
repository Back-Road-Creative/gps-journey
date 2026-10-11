"""Every CLI command at least builds and answers ``--help``.

``gps-journey`` uses Typer, not bare argparse -- there is no
``parser._subparsers`` to walk here. Typer's ``app.registered_commands``
gives the command objects, but ``CommandInfo.name`` is ``None`` for every
command in this app (none of them pass an explicit ``name=`` to
``@app.command()``) -- Typer derives the CLI-visible name from the callback
function name at invocation time, converting underscores to hyphens
(``export_metadata`` -> ``export-metadata``). So discovery derives the name
the same way and verifies it by actually invoking ``--help`` through
``typer.testing.CliRunner``, which drives the real Click-based dispatch
(exit code 0, non-empty output) rather than trusting the derivation alone.

This app has no command groups, so there is nothing to recurse into.
"""

import pytest
from typer.testing import CliRunner

from gps_journey.cli import app

runner = CliRunner()


def _derived_name(callback) -> str:
    return callback.__name__.replace("_", "-")


COMMAND_NAMES = sorted(_derived_name(c.callback) for c in app.registered_commands)


def test_discovery_found_commands():
    assert COMMAND_NAMES == ["export-metadata", "process", "validate", "version"]


@pytest.mark.parametrize("name", COMMAND_NAMES)
def test_command_help_builds_and_exits_zero(name):
    result = runner.invoke(app, [name, "--help"])
    assert result.exit_code == 0
    assert result.output.strip() != ""


def test_top_level_help_builds_and_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert result.output.strip() != ""
