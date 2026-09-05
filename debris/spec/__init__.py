"""The JSON spec: dataclasses, loader, and hand-written validator.

Debris targets machines with no internet, where a broken package is expensive to diagnose
and awkward to replace. The rule here follows from that: anything checkable at build time
gets checked at build time, and every message names the exact JSON path that is wrong.

Validation is hand-written rather than delegated to `jsonschema` because a runtime
dependency would have to be mirrored into the closed network (see CLAUDE.md). That trade
buys something beyond dependency hygiene: a schema cannot express the cross-field rules in
`crosscheck.py`, and those are the ones that actually prevent broken installs.

The pieces, in dependency order:

    patterns.py    what a value may be -- enumerations, regexes and their prose
    values.py      why one value is unusable, whatever key it arrived under
    problems.py    the collected report
    reader.py      typed access to one JSON object, recording instead of raising
    model.py       the dataclasses, and the keys each section accepts
    sections.py    one reader per section, holding that section's defaults
    crosscheck.py  the rules that span sections
    loader.py      parse, read, cross-check, raise

Only the names below are imported from elsewhere in Debris; everything else is internal to
this package and may move between its modules.
"""

from debris.spec.loader import load_spec
from debris.spec.model import (
    Deployment,
    DesktopEntry,
    Env,
    ExtraFile,
    Helpers,
    Hooks,
    Install,
    Package,
    Registry,
    Source,
    Spec,
)
from debris.spec.patterns import (
    ENV_KEY,
    ENV_KEY_EXPECTED,
    HELPER_COMMANDS,
    MODES,
    PACKAGE_NAME,
    PACKAGE_NAME_EXPECTED,
    SCHEMA_VERSION,
)

__all__ = [
    "Deployment",
    "DesktopEntry",
    "ENV_KEY",
    "ENV_KEY_EXPECTED",
    "Env",
    "ExtraFile",
    "HELPER_COMMANDS",
    "Helpers",
    "Hooks",
    "Install",
    "MODES",
    "PACKAGE_NAME",
    "PACKAGE_NAME_EXPECTED",
    "Package",
    "Registry",
    "SCHEMA_VERSION",
    "Source",
    "Spec",
    "load_spec",
]
