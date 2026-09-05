"""Reading a spec file end to end: parse, read every section, cross-check, report.

This is the only module that decides when validation is over. `_read` fills a Spec while
`_Problems` collects, `_cross_check` then runs against the filled Spec, and only after
both is the report raised. The order is deliberate: a cross-field rule needs every section
present, so it cannot run from inside a section reader.
"""

import json
from pathlib import Path
from typing import Any

from debris.errors import SpecError
from debris.spec.crosscheck import _cross_check
from debris.spec.model import Spec, _ROOT_KEYS
from debris.spec.patterns import MODES, SCHEMA_VERSION
from debris.spec.problems import _Problems
from debris.spec.reader import _Reader, _kind_of
from debris.spec.sections import (
    _read_deployment,
    _read_desktop_entry,
    _read_file,
    _read_helpers,
    _read_hooks,
    _read_install,
    _read_package,
)


def load_spec(path: str | Path, *, mode: str | None = None) -> Spec:
    """Read, default and validate a spec file.

    `mode` is the `--mode` override. It is applied before validation because it decides
    which cross-field rules apply: building a spec that says `online` with `--mode offline`
    still needs a non-empty image list.

    Raises `SpecError` listing every problem found.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SpecError(f"{path}: no such file") from None
    except IsADirectoryError:
        raise SpecError(f"{path}: is a directory, not a spec file") from None
    except OSError as exc:
        raise SpecError(f"{path}: {exc.strerror or exc}") from None

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SpecError(f"{path}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}") from None

    if not isinstance(data, dict):
        raise SpecError(f"{path}: expected a JSON object, got {_kind_of(data)}")

    if mode is not None and mode not in MODES:
        raise SpecError(f"unknown mode {mode!r}: expected one of {', '.join(MODES)}")

    problems = _Problems()
    spec = _read(data, path, mode, problems)
    _cross_check(spec, problems)
    if problems:
        raise SpecError(_format_problems(path, problems))
    return spec


def _format_problems(path: Path, problems: _Problems) -> str:
    unique = list(dict.fromkeys(problems.items))
    heading = f"{path}: {len(unique)} problem{'' if len(unique) == 1 else 's'}"
    return "\n".join([heading, *(f"  {problem}" for problem in unique)])


def _read(data: dict[str, Any], path: Path, mode: str | None, problems: _Problems) -> Spec:
    root = _Reader(data, "", problems)

    schema_version = _check_schema_version(root)
    package = _read_package(root.child("package", required=True))
    install = _read_install(root.child("install"), package)
    deployment = _read_deployment(root.child("deployment", required=True), mode)
    helpers = _read_helpers(root.child("helpers"), package)
    desktop_entries = [
        _read_desktop_entry(reader) for reader in root.children("desktop_entries")
    ]
    files = [_read_file(reader) for reader in root.children("files")]
    hooks = _read_hooks(root.child("hooks"))

    root.reject_unknown(*_ROOT_KEYS)

    return Spec(
        schema_version=schema_version,
        package=package,
        install=install,
        deployment=deployment,
        helpers=helpers,
        desktop_entries=desktop_entries,
        files=files,
        hooks=hooks,
        spec_path=path,
    )


def _check_schema_version(root: _Reader) -> int | None:
    """The declared version, plus a complaint when this Debris cannot read it."""
    schema_version = root.integer("schema_version")
    if schema_version is not None and schema_version != SCHEMA_VERSION:
        root.problem(
            f"unsupported schema version {schema_version}; this Debris understands "
            f"{SCHEMA_VERSION}",
            "schema_version",
        )
    return schema_version
