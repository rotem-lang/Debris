"""Command line interface for Debris.

The parser declares the whole surface, including flags whose machinery has not landed yet,
so the CLI contract stays reviewable ahead of the code behind it. `build` and `inspect` are
still stubs; the status table in CLAUDE.md says which branch each lands on.
"""

import argparse
import sys
from collections.abc import Sequence
from typing import NoReturn

from debris import __version__
from debris.errors import DebrisError
from debris.scaffold import write_scaffold
from debris.spec import ENV_KEY, ENV_KEY_EXPECTED, Spec, load_spec

EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


def _key_value(text: str) -> tuple[str, str]:
    """Parse a `--var KEY=VALUE` argument.

    The name is held to the same rule as `deployment.env.vars`, so an override cannot
    introduce something the spec itself would have rejected.
    """
    key, sep, value = text.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {text!r}")
    if not ENV_KEY.match(key):
        raise argparse.ArgumentTypeError(
            f"invalid environment variable name {key!r}: expected {ENV_KEY_EXPECTED}"
        )
    return key, value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        # Debris is never installed, so there is no `debris` executable to name here.
        # argparse only detects `python -m` by itself from 3.14 on.
        prog="python3 -m debris",
        description="Build Debian packages for docker-compose applications from a JSON spec.",
    )
    parser.add_argument("--version", action="version", version=f"debris {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    validate = sub.add_parser("validate", help="check a spec file without touching the network")
    validate.add_argument("spec", help="path to the JSON spec")
    validate.set_defaults(func=cmd_validate)

    _add_build_command(sub)

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


def _add_build_command(sub: argparse._SubParsersAction) -> None:
    """`build` alone, because it carries every flag the other three subcommands do not."""
    build = sub.add_parser("build", help="build a .deb from a spec file")
    build.add_argument("spec", help="path to the JSON spec")
    build.add_argument(
        "-o", "--output-dir", default="dist", help="where to write the .deb (default: dist)"
    )
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
        help=(
            "use a local checkout instead of fetching from git "
            "(air-gapped build hosts, tests)"
        ),
    )
    build.add_argument("--work-dir", help="staging directory (default: a temporary directory)")
    build.add_argument(
        "--keep-work",
        action="store_true",
        help="do not delete the staging directory, for debugging a build",
    )
    build.set_defaults(func=cmd_build)


def _todo(command: str, branch: str) -> NoReturn:
    raise DebrisError(
        f"`python3 -m debris {command}` is not implemented yet; it lands on {branch}"
    )


def cmd_validate(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    print(f"{spec.spec_path}: ok")
    for line in summarise(spec):
        print(f"  {line}")
    return 0


def summarise(spec: Spec) -> list[str]:
    """The resolved spec, defaults included.

    Printing this is most of the value of `validate`: the defaults are what a build will
    actually use, and they are invisible in the file itself.
    """
    deployment = spec.deployment
    source = deployment.source
    if source.kind == "git":
        where = f"git {source.url} @ {source.ref}"
        if source.path:
            where += f" ({source.path}/)"
    else:
        where = f"local {source.path}"

    lines = [
        f"package   {spec.package.name} {spec.package.version} ({spec.package.architecture})",
        f"install   {spec.install.target_dir}",
        f"source    {where}",
        f"mode      {deployment.mode}",
    ]
    if deployment.mode == "offline":
        lines.append(f"images    {len(deployment.images)} baked into the package")
    elif deployment.registry.host:
        lines.append(f"registry  {deployment.registry.host}")
    if deployment.env.template:
        lines.append(
            f"env       {deployment.env.template} -> {deployment.env.output} "
            f"({len(deployment.env.vars)} variables)"
        )
    if spec.helpers.enabled:
        lines.append(f"helpers   {', '.join(spec.helpers.command_names())}")
    for entry in spec.desktop_entries:
        lines.append(f"desktop   {entry.filename} runs {entry.exec!r}")
    for item in spec.files:
        lines.append(f"file      {item.source} -> {item.dest} ({item.mode})")
    return lines


def cmd_build(args: argparse.Namespace) -> int:
    return _todo("build", "feat/deb-build")


def cmd_init(args: argparse.Namespace) -> int:
    path = write_scaffold(args.name, is_offline=args.offline)
    print(f"wrote {path}")
    print(f"edit it, then run: python3 -m debris validate {path}")
    return 0


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
        return EXIT_INTERRUPTED
