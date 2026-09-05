"""Rules that span more than one key, run once every section has been read.

These are the reason validation is hand-written rather than delegated to a JSON schema:
each one catches a spec that is structurally fine but produces a package that fails on the
target machine.

Every check guards its own inputs against None. A reader hands back None for a value it
rejected, and these run while those problems are still outstanding -- so an unguarded check
would crash on a spec it was written to complain about, and the user would get a traceback
instead of the report.
"""

from pathlib import Path, PurePosixPath

from debris.spec.model import Spec
from debris.spec.problems import _Problems


def _cross_check(spec: Spec, problems: _Problems) -> None:
    """Every cross-field rule, in the order their complaints should be reported."""
    _check_mode_requirements(spec, problems)
    _check_env_has_a_target(spec, problems)
    _check_desktop_entries(spec, problems)
    _check_install_collisions(spec, problems)
    _check_unique(
        [entry.filename for entry in spec.desktop_entries],
        "desktop_entries",
        "filename",
        "two entries would install to the same path in /usr/share/applications",
        problems,
    )
    _check_unique(
        [item.dest for item in spec.files],
        "files",
        "dest",
        "two files would install to the same path",
        problems,
    )
    _check_paths_exist(spec, problems)


def _check_mode_requirements(spec: Spec, problems: _Problems) -> None:
    """What the chosen mode needs before the package it builds can install."""
    deployment = spec.deployment

    if deployment.mode == "offline" and deployment.images is not None and not deployment.images:
        problems.add(
            "deployment.images",
            'mode "offline" bakes the images into the .deb, so at least one image is required',
        )
    if (
            deployment.mode == "online"
            and not deployment.registry.host
            and "deployment.registry.host" not in problems.failed
    ):
        problems.add(
            "deployment.registry.host",
            'mode "online" pulls at install time, so the internal registry host is required',
        )


def _check_env_has_a_target(spec: Spec, problems: _Problems) -> None:
    """Variables with nothing to substitute them into.

    `render_templates` is substituted from the same variables, so vars are still useful
    for an app that ships no `.env` at all.
    """
    deployment = spec.deployment

    if (
            deployment.env.vars
            and deployment.env.template is None
            and not deployment.render_templates
            and "deployment.env.template" not in problems.failed
    ):
        problems.add(
            "deployment.env.vars",
            "there is nothing to substitute into: neither deployment.env.template nor "
            "deployment.render_templates is set",
        )


def _check_desktop_entries(spec: Spec, problems: _Problems) -> None:
    """A launcher that runs a helper Debris does not generate is a dead button."""
    helpers = spec.helpers
    if not helpers.prefix or helpers.commands is None or helpers.enabled is None:
        return
    generated = set(helpers.command_names()) if helpers.enabled else set()

    for index, entry in enumerate(spec.desktop_entries):
        if not entry.exec:
            continue
        words = entry.exec.split()
        if not words:
            continue
        # `Exec=` is frequently an absolute path, and '/usr/bin/<pkg>-restart' is just as
        # dead as the bare name if no such helper is generated.
        program = PurePosixPath(words[0]).name
        if not program.startswith(f"{helpers.prefix}-") or program in generated:
            continue
        where = f"desktop_entries[{index}].exec"
        if not helpers.enabled:
            problems.add(
                where,
                f"runs {program!r}, but helpers.enabled is false so no helper is installed",
            )
        else:
            problems.add(
                where,
                f"runs {program!r}, which is not one of the generated helpers "
                f"({', '.join(sorted(generated))})",
            )


def _check_install_collisions(spec: Spec, problems: _Problems) -> None:
    """Two things in the package claiming one path on disk."""
    install = spec.install
    if install.current_symlink and install.version_dir == "current":
        problems.add(
            "install.version_dir",
            "'current' is the name of the symlink that points at the version directory, so "
            "the two would be the same path; set install.current_symlink to false or pick "
            "another name",
        )

    if spec.helpers.enabled and spec.helpers.commands is not None and spec.helpers.prefix:
        helper_paths = {f"/usr/bin/{name}" for name in spec.helpers.command_names()}
    else:
        helper_paths = set()

    for index, item in enumerate(spec.files):
        if not item.dest:
            continue
        if item.dest in helper_paths:
            problems.add(
                f"files[{index}].dest",
                f"{item.dest!r} is also a generated helper; rename the file or drop that "
                "command from helpers.commands",
            )
        elif item.dest == install.current_dir:
            problems.add(
                f"files[{index}].dest",
                f"{item.dest!r} is the 'current' symlink this package ships",
            )


def _check_unique(
        values: list[str], section: str, key: str, why: str, problems: _Problems
) -> None:
    seen: dict[str, int] = {}
    for index, value in enumerate(values):
        if value is None:
            continue
        if value in seen:
            problems.add(
                f"{section}[{index}].{key}",
                f"{value!r} is already used by {section}[{seen[value]}]; {why}",
            )
            continue
        seen[value] = index


def _check_paths_exist(spec: Spec, problems: _Problems) -> None:
    """Everything resolved against the spec's own directory has to be there now.

    The fetched source cannot be checked without the network, but these files sit next to
    the spec, so a missing one is a mistake worth catching before a build starts.
    """
    base = spec.directory

    for index, item in enumerate(spec.files):
        if item.source and not (base / item.source).is_file():
            problems.add(f"files[{index}].source", f"{item.source!r} does not exist in {base}")

    for name in ("postinst", "prerm", "postrm"):
        hook = getattr(spec.hooks, name)
        if hook and not (base / hook).is_file():
            problems.add(f"hooks.{name}", f"{hook!r} does not exist in {base}")

    source = spec.deployment.source
    if source.kind == "local" and source.path:
        directory = Path(source.path)
        resolved = directory if directory.is_absolute() else base / directory
        if not resolved.is_dir():
            problems.add(
                "deployment.source.path",
                f"{source.path!r} is not a directory (looked in {resolved})",
            )
