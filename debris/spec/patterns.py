"""The vocabulary a spec is checked against: enumerations, patterns and their prose.

These sit apart from the readers because they describe what a value may *be*, not how it
is pulled out of the JSON. `schema/debris.schema.json` mirrors them for editor
autocomplete and `tests/test_schema.py` is what keeps the two in step, so a pattern here
is read by more than the loader.

Every `_EXPECTED` string completes the sentence "<value> is not ...", so it names what was
wanted rather than repeating what was wrong.
"""

import re

SCHEMA_VERSION = 1

#: Backends implemented today. `sources/` and `backends/` are registries precisely so this
#: tuple grows without the CLI or the packaging code changing.
BACKEND_KINDS = ("compose",)
SOURCE_KINDS = ("git", "local")
MODES = ("online", "offline")

#: Canonical order, also the default set. `compose` is the admin escape hatch that passes
#: its arguments straight through.
HELPER_COMMANDS = ("start", "stop", "restart", "status", "logs", "compose")

_PRIORITIES = ("required", "important", "standard", "optional", "extra")

# Debian policy 5.6.1: at least two characters, lowercase alphanumerics plus + - .
PACKAGE_NAME = re.compile(r"[a-z0-9][a-z0-9+.-]+\Z")
PACKAGE_NAME_EXPECTED = (
    "a Debian package name: two or more characters, lowercase letters, digits, '+', '-' "
    "and '.', starting with a letter or digit"
)

# Debian policy 5.6.12, minus the epoch. Epochs would have to be stripped again to build a
# filename, and nothing Debris packages needs one. Note the repeated hyphen group: dpkg
# splits on the *last* hyphen, so '1.4.2-rc1-1' is an upstream pre-release plus a Debian
# revision and is perfectly legal -- allowing only one hyphen would refuse to package it.
_VERSION = re.compile(r"[0-9][A-Za-z0-9.+~]*(-[A-Za-z0-9.+~]+)*\Z")
_VERSION_EXPECTED = "a Debian version such as '1.4.2' or '1.4.2-1' (epochs are not supported)"

_ARCHITECTURE = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*\Z")
# The name part must start with something other than whitespace, or ' <a@b>' passes.
_MAINTAINER = re.compile(r"\S[^<>]*<[^<>@\s]+@[^<>@\s]+>\Z")
# '~' is in both classes because it is legal in a version, and `version_dir` defaults to
# `package.version`: without it, writing out the value it already defaults to is rejected.
_ABSOLUTE_PATH = re.compile(r"(/[A-Za-z0-9._+~-]+)+\Z")
_PATH_SEGMENT = re.compile(r"[A-Za-z0-9._+~-]+\Z")
# '+' is allowed because a package name may contain it, and `debris init` derives the
# launcher filename from the package name.
_DESKTOP_FILENAME = re.compile(r"[A-Za-z0-9._+-]+\.desktop\Z")
# Three octal digits only. setuid, setgid and sticky are deliberately out of reach: dpkg
# would need a `dpkg-statoverride` to manage them properly, nothing Debris ships needs one,
# and a spec file is the wrong place to grant them by accident.
_FILE_MODE = re.compile(r"0?[0-7]{3}\Z")
_FILE_MODE_EXPECTED = (
    "a three-digit octal mode such as '0644' (setuid, setgid and sticky bits are not "
    "supported)"
)
_REGISTRY_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{1,5})?\Z")

#: A name that both `.env` and `docker compose --env-file` accept. `cli.py` reuses this so
#: `--var` and `deployment.env.vars` cannot disagree about what a variable may be called.
ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
ENV_KEY_RULE = "a letter or underscore followed by letters, digits or underscores"
ENV_KEY_EXPECTED = f"an environment variable name: {ENV_KEY_RULE}"
