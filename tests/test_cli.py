"""Smoke tests for the CLI surface.

These lock in the command contract (names, flags, exit codes) before the machinery behind
it exists, so later branches can only extend it, not silently reshape it.
"""

import pytest

from debris.cli import EXIT_ERROR, EXIT_USAGE, _key_value, build_parser, main


def test_no_command_prints_usage(capsys):
    assert main([]) == EXIT_USAGE
    assert "usage:" in capsys.readouterr().err


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "debris" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["validate", "spec.json"],
        ["build", "spec.json"],
        ["init", "demo"],
        ["inspect", "pkg.deb"],
    ],
)
def test_unimplemented_commands_fail_cleanly(argv, capsys):
    """A stub must report a DebrisError, not leak a traceback."""
    assert main(argv) == EXIT_ERROR
    assert "not implemented yet" in capsys.readouterr().err


def test_build_parses_repeatable_var():
    args = build_parser().parse_args(
        ["build", "spec.json", "--var", "A=1", "--var", "B=x=y", "--var", "C="]
    )
    assert args.var == [("A", "1"), ("B", "x=y"), ("C", "")]


@pytest.mark.parametrize("bad", ["novalue", "=novalue"])
def test_var_rejects_malformed_pairs(bad):
    with pytest.raises(Exception, match="KEY=VALUE"):
        _key_value(bad)


def test_build_defaults():
    args = build_parser().parse_args(["build", "spec.json"])
    assert args.output_dir == "dist"
    assert args.mode is None
    assert args.source_dir is None
    assert args.keep_work is False
