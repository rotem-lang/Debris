"""Smoke tests for the CLI surface.

These lock in the command contract (names, flags, exit codes) before the machinery behind
it exists, so later branches can only extend it, not silently reshape it.
"""

import argparse

import pytest

from debris import cli
from debris.cli import (
    EXIT_ERROR,
    EXIT_INTERRUPTED,
    EXIT_USAGE,
    _key_value,
    build_parser,
    main,
)


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


@pytest.mark.parametrize("bad", ["novalue", ""])
def test_var_rejects_missing_separator(bad):
    with pytest.raises(argparse.ArgumentTypeError, match="KEY=VALUE"):
        _key_value(bad)


@pytest.mark.parametrize("bad", ["=novalue", "MY KEY=1", "2BAD=x", "$X=1", "  =1"])
def test_var_rejects_names_a_dotenv_file_cannot_hold(bad):
    with pytest.raises(argparse.ArgumentTypeError, match="invalid environment variable name"):
        _key_value(bad)


@pytest.mark.parametrize(
    "argv",
    [
        ["build", "spec.json", "--var", "novalue"],
        ["build", "spec.json", "--mode", "weird"],
        ["frobnicate"],
    ],
)
def test_argparse_rejections_exit_usage(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == EXIT_USAGE


def test_keyboard_interrupt_is_distinct_from_error(monkeypatch, capsys):
    def interrupt(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_build", interrupt)
    assert main(["build", "spec.json"]) == EXIT_INTERRUPTED
    assert "interrupted" in capsys.readouterr().err


def test_build_defaults():
    args = build_parser().parse_args(["build", "spec.json"])
    assert args.output_dir == "dist"
    assert args.mode is None
    assert args.var == []
    assert args.source_dir is None
    assert args.work_dir is None
    assert args.keep_work is False
