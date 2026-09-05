"""Keep `schema/debris.schema.json` in step with the validator.

The schema is editor autocomplete only -- Debris never reads it, because `jsonschema` would
be a runtime dependency to mirror into the closed network. That makes it exactly the kind
of file that rots: nothing breaks when it drifts, it just starts lying to whoever is
writing a spec. These tests are the substitute for it being load-bearing.

They cannot check the cross-field rules, which JSON Schema cannot express anyway. They
check the parts that are mechanically comparable: the patterns and the defaults.
"""

import json
import re
from pathlib import Path

import pytest

from debris.spec import HELPER_COMMANDS, MODES, SCHEMA_VERSION, patterns

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "debris.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def at(schema: dict, path: str) -> dict:
    """Walk a dotted path of `properties` keys, e.g. 'package.name'."""
    node = schema
    for part in path.split("."):
        node = node["properties"][part]
    return node


#: Schema location -> the compiled pattern in `debris/spec/patterns.py` it mirrors.
MIRRORED_PATTERNS = {
    "package.name": patterns.PACKAGE_NAME,
    "package.version": patterns._VERSION,
    "package.architecture": patterns._ARCHITECTURE,
    "package.maintainer": patterns._MAINTAINER,
    "install.prefix": patterns._ABSOLUTE_PATH,
    "install.dir_name": patterns.PACKAGE_NAME,
    "install.version_dir": patterns._PATH_SEGMENT,
    "deployment.registry.host": patterns._REGISTRY_HOST,
    "helpers.prefix": patterns.PACKAGE_NAME,
}


@pytest.mark.parametrize("location", sorted(MIRRORED_PATTERNS))
def test_patterns_match_the_validator(schema, location):
    """The schema spells the same rule with `^...$` rather than `\\Z`.

    `\\Z` is Python's end-of-string anchor and is not valid in the ECMAScript regexes JSON
    Schema uses.
    """
    expected = "^" + MIRRORED_PATTERNS[location].pattern.removesuffix(r"\Z") + "$"
    assert at(schema, location)["pattern"] == expected


def test_nested_patterns_match_the_validator(schema):
    desktop = schema["properties"]["desktop_entries"]["items"]["properties"]
    files = schema["properties"]["files"]["items"]["properties"]
    env_vars = at(schema, "deployment.env.vars")

    assert desktop["filename"]["pattern"] == "^" + _anchored(patterns._DESKTOP_FILENAME)
    assert files["mode"]["pattern"] == "^" + _anchored(patterns._FILE_MODE)
    assert env_vars["propertyNames"]["pattern"] == "^" + _anchored(patterns.ENV_KEY)


def _anchored(pattern: re.Pattern[str]) -> str:
    return pattern.pattern.removesuffix(r"\Z") + "$"


def test_defaults_match_the_loader(schema, tmp_path):
    """A default the loader does not apply is worse than no default at all.

    The editor shows one value and the build uses another.
    """
    from tests.test_spec import load, minimal

    loaded = load(tmp_path, minimal())

    assert at(schema, "deployment.mode")["default"] == loaded.deployment.mode
    assert at(schema, "install.prefix")["default"] == loaded.install.prefix
    assert at(schema, "install.current_symlink")["default"] == loaded.install.current_symlink
    assert at(schema, "install.start_on_install")["default"] == loaded.install.start_on_install
    assert at(schema, "install.stop_on_remove")["default"] == loaded.install.stop_on_remove
    assert at(schema, "deployment.compose_files")["default"] == loaded.deployment.compose_files
    assert at(schema, "deployment.env.template")["default"] == loaded.deployment.env.template
    assert at(schema, "deployment.env.output")["default"] == loaded.deployment.env.output
    assert at(schema, "helpers.commands")["default"] == loaded.helpers.commands
    assert at(schema, "package.architecture")["default"] == loaded.package.architecture
    assert at(schema, "package.priority")["default"] == loaded.package.priority


def test_enums_match_the_validator(schema):
    assert at(schema, "schema_version")["const"] == SCHEMA_VERSION
    assert at(schema, "deployment.mode")["enum"] == list(MODES)
    assert at(schema, "deployment.kind")["enum"] == list(patterns.BACKEND_KINDS)
    assert at(schema, "deployment.source.kind")["enum"] == list(patterns.SOURCE_KINDS)
    assert at(schema, "package.priority")["enum"] == list(patterns._PRIORITIES)

    commands = at(schema, "helpers.commands")
    assert commands["items"]["enum"] == list(HELPER_COMMANDS)


def test_schema_knows_every_key_the_loader_accepts(schema):
    """A key the loader accepts but the schema omits gets flagged as an error in the editor.

    That is the failure mode most likely to send someone looking for a bug in their spec.
    """
    assert set(schema["properties"]) == {
        "schema_version",
        "package",
        "install",
        "deployment",
        "helpers",
        "desktop_entries",
        "files",
        "hooks",
    }
    assert set(at(schema, "package")["properties"]) == {
        "name",
        "version",
        "architecture",
        "maintainer",
        "description",
        "long_description",
        "section",
        "priority",
        "homepage",
        "depends",
        "recommends",
        "conflicts",
        "replaces",
    }
    assert set(at(schema, "deployment")["properties"]) == {
        "kind",
        "mode",
        "source",
        "compose_files",
        "extra_files",
        "render_templates",
        "env",
        "registry",
        "images",
        "remove_image_archive_after_load",
    }


def test_every_object_rejects_unknown_keys(schema):
    """The loader reports unknown keys, so the schema has to as well.

    Otherwise the editor happily autocompletes a typo the build then refuses.
    """
    unchecked = list(_objects(schema))
    assert unchecked, "no objects found -- the walk is broken"
    for where, node in unchecked:
        assert node.get("additionalProperties") is False, f"{where} allows unknown keys"


def _objects(node, where="<root>"):
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            yield where, node
        for key, value in node.items():
            if key in ("properties", "items", "additionalProperties", "propertyNames"):
                yield from _objects(value, f"{where}.{key}")
            elif isinstance(value, dict) and key not in ("default", "$comment"):
                yield from _objects(value, f"{where}.{key}")


def test_the_schema_says_it_is_not_used_at_runtime(schema):
    """Anyone finding this file should learn immediately that spec.py is authoritative."""
    assert "debris/spec.py" in schema["$comment"]
