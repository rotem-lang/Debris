"""Command line interface for Debris.

The parser is complete; the command implementations land on their own branches (see the
status table in CLAUDE.md). Keeping the full surface declared here means the CLI contract
is reviewable before any of the machinery behind it exists.
"""

import argparse
import sys
from collections.abc import Sequence

from debris import __version__
from debris.errors import DebrisError

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def _key_value(text: str) -> tuple[str, str]:
    """Parse a `--var KEY=VALUE` argument."""
    key, sep, value = text.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {text!r}")
    return key, value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="debris",
        description="Build Debian packages for docker-compose applications from a JSON spec.",
    )
    parser.add_argument("--version", action="version", version=f"debris {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    validate = sub.add_parser("validate", help="check a spec file without touching the network")
    validate.add_argument("spec", help="path to the JSON spec")
    validate.set_defaults(func=cmd_validate)

    build = sub.add_parser("build", help="build a .deb from a spec file")
    build.add_argument("spec", help="path to the JSON spec")
    build.add_argument("-o", "--output-dir", default="dist", help="where to write the .deb")
    build.add_argument(
        "--mode",
        choices=("online", "offline"),
        help="override deployment.mode from the spec",
    )
    build.add_argument(
        "--var",
        action="append",
        default=[],
        type=_key_value,
        metavar="KEY=VALUE",
        help="override an entry in deployment.env.vars (repeatable)",
    )
    build.add_argument(
        "--source-dir",
        help="use a local checkout instead of fetching the source (offline builds, tests)",
    )
    build.add_argument("--work-dir", help="staging directory (default: a temporary directory)")
    build.add_argument(
        "--keep-work",
        action="store_true",
        help="do not delete the staging directory, for debugging a build",
    )
    build.set_defaults(func=cmd_build)

    init = sub.add_parser("init", help="scaffold a new spec file")
    init.add_argument("name", help="package name, also used as the directory name")
    init.add_argument(
        "--offline",
        action="store_true",
        help="scaffold an offline-mode spec with a baked image list",
    )
    init.set_defaults(func=cmd_init)

    inspect = sub.add_parser("inspect", help="print the manifest embedded in a .deb")
    inspect.add_argument("deb", help="path to a .deb built by Debris")
    inspect.set_defaults(func=cmd_inspect)

    return parser


def _todo(command: str, branch: str) -> int:
    raise DebrisError(f"`debris {command}` is not implemented yet; it lands on {branch}")


def cmd_validate(args: argparse.Namespace) -> int:
    return _todo("validate", "feat/spec-validation")


def cmd_build(args: argparse.Namespace) -> int:
    return _todo("build", "feat/deb-build")


def cmd_init(args: argparse.Namespace) -> int:
    return _todo("init", "feat/spec-validation")


def cmd_inspect(args: argparse.Namespace) -> int:
    return _todo("inspect", "feat/deb-build")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "func", None):
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    try:
        return args.func(args)
    except DebrisError as exc:
        print(f"debris: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("debris: interrupted", file=sys.stderr)
        return EXIT_ERROR
