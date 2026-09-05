"""Smoke tests for the CLI surface.

These lock in the command contract (names, flags, exit codes) before the machinery behind
it exists, so later branches can only extend it, not silently reshape it.
"""

import argparse
import json

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


@pytest.mark.parametrize("argv", [["build", "spec.json"], ["inspect", "pkg.deb"]])
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


def test_init_then_validate(tmp_path, monkeypatch, capsys):
    """The loop a new user runs first.

    `init` writes into the working directory, so this also pins down that it does not
    write to the spec's own location or to $HOME.
    """
    monkeypatch.chdir(tmp_path)

    assert main(["init", "acme-portal"]) == 0
    assert (tmp_path / "acme-portal" / "spec.json").is_file()

    capsys.readouterr()
    assert main(["validate", "acme-portal/spec.json"]) == 0
    out = capsys.readouterr().out
    assert ": ok" in out
    assert "acme-portal 0.1.0 (all)" in out


def test_init_offline_scaffolds_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["init", "acme-portal", "--offline"])
    capsys.readouterr()

    main(["validate", "acme-portal/spec.json"])
    assert "mode      offline" in capsys.readouterr().out


def test_validate_reports_every_problem_and_exits_one(tmp_path, capsys):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"schema_version": 1}))

    assert main(["validate", str(spec)]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "debris: error:" in err
    assert "package: required key is missing" in err
    assert "deployment: required key is missing" in err


def test_validate_prints_the_resolved_defaults(tmp_path, capsys):
    """The defaults are what a build will use, and they are invisible in the file.

    That `validate` prints them is most of what makes it worth running.
    """
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "package": {
                    "name": "acme-portal",
                    "version": "1.4.2",
                    "maintainer": "Ops <ops@corp.local>",
                    "description": "ACME Portal",
                },
                "deployment": {
                    "source": {"kind": "git", "url": "ssh://git/a.git", "ref": "v1.4.2"},
                    "images": ["registry.corp.local:5000/acme/portal:1.4.2"],
                },
            }
        )
    )

    assert main(["validate", str(spec)]) == 0
    out = capsys.readouterr().out
    assert "install   /opt/acme-portal/1.4.2" in out
    assert "mode      offline" in out
    assert "acme-portal-restart" in out


def test_init_refusing_to_overwrite_is_a_clean_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["init", "acme-portal"])

    assert main(["init", "acme-portal"]) == EXIT_ERROR
    assert "already exists" in capsys.readouterr().err
