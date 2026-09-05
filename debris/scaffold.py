"""`debris init` -- write a starter spec.

The scaffold is deliberately a working spec rather than a skeleton of empty strings: it
passes `debris validate` as written, so the first thing a new user does succeeds and they
edit from something that runs. The placeholder hostnames are obviously internal names,
which makes them easy to spot and replace.
"""

import json
from pathlib import Path

from debris.errors import SpecError
from debris.spec import HELPER_COMMANDS, PACKAGE_NAME, PACKAGE_NAME_EXPECTED, SCHEMA_VERSION

SPEC_FILENAME = "spec.json"

_REGISTRY = "registry.corp.local:5000"
_GIT_HOST = "git.corp.local"
_VERSION = "0.1.0"


def scaffold_spec(name: str, *args, offline: bool) -> dict:
    """The spec `debris init` writes, as plain data so tests can assert on it."""
    return {
        "schema_version": SCHEMA_VERSION,
        "package": _package_section(name),
        "install": _install_section(),
        "deployment": _deployment_section(name, offline=offline),
        "helpers": _helpers_section(name),
        "desktop_entries": [_restart_entry(name)],
        "files": [],
    }


def _package_section(name: str) -> dict:
    return {
        "name": name,
        "version": _VERSION,
        "architecture": "all",
        "maintainer": "<ops@corp.local>",
        "description": "<package-description>",
        "depends": ["docker-ce", "docker-compose-plugin"],
    }


def _install_section() -> dict:
    return {
        "prefix": "/opt",
        # The admin runs `<name>-start`; containers coming up unannounced during an
        # `apt install` is surprising.
        "start_on_install": False,
        "stop_on_remove": True,
    }


def _deployment_section(name: str, *, offline: bool) -> dict:
    """The compose backend, plus the keys that only one of the two modes uses."""
    if offline:
        # Offline bakes the images in, so the list has to be explicit -- Debris will not
        # parse them out of the compose file (that would need a YAML dependency).
        mode_keys = {
            "images": [f"{_REGISTRY}/{name}/app:{_VERSION}"],
            "remove_image_archive_after_load": False,
        }
    else:
        mode_keys = {"registry": {"host": _REGISTRY, "require_login": False}}

    return {
        "kind": "compose",
        "mode": "offline" if offline else "online",
        "source": {
            "kind": "git",
            "url": f"ssh://git@{_GIT_HOST}/apps/{name}.git",
            "ref": f"v{_VERSION}",
            "path": "deploy",
        },
        "compose_files": ["docker-compose.yml"],
        "env": {
            "template": ".env.template",
            "output": ".env",
            "strict": True,
            "vars": {
                "APP_VERSION": _VERSION,
                "REGISTRY": _REGISTRY,
                # Runtime data must live outside /opt/<pkg>/<version>/, which dpkg
                # deletes on upgrade. Pass the path in instead of bind-mounting there.
                "DATA_DIR": f"/var/lib/{name}",
            },
        },
        **mode_keys,
    }


def _helpers_section(name: str) -> dict:
    return {
        "enabled": True,
        "prefix": name,
        "commands": list(HELPER_COMMANDS),
    }


def _restart_entry(name: str) -> dict:
    """A launcher for a helper the scaffold also generates, which the validator checks."""
    return {
        "filename": f"{name}-restart.desktop",
        "name": f"Restart {name}",
        "comment": f"Restart the {name} stack",
        "exec": f"{name}-restart",
        "terminal": True,
        "categories": ["System", "Utility"],
    }


def write_scaffold(name: str, *args, is_offline: bool = True, directory: Path | None = None) -> Path:
    """Create `<name>/spec.json` and return its path.

    Refuses to overwrite an existing spec: `init` is for starting, and clobbering an edited
    spec would lose work that cannot be recovered from git if it was never committed.
    """
    if not PACKAGE_NAME.match(name):
        raise SpecError(
            f"{name!r} is not {PACKAGE_NAME_EXPECTED}; the name becomes the package name, "
            "the install directory and the helper prefix"
        )

    target = (directory or Path.cwd()) / name
    path = target / SPEC_FILENAME
    if path.exists():
        raise SpecError(f"{path}: already exists; delete it or choose another name")

    target.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scaffold_spec(name, offline=is_offline), indent=4) + "\n")
    return path
