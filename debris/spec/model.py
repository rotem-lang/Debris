"""The shape of a spec: one dataclass per section, and the keys each section accepts.

No field carries a default. Every default lives in the loader instead, in one place, so
`deployment.mode` cannot end up with one value here and another there -- the failure mode
that made `--mode` an override with no argparse default (see CLAUDE.md).

Each section also names its keys as a `_*_KEYS` tuple, which is what the reader hands to
`reject_unknown`. The tuple sits beside its dataclass because the two have to agree: a key
the dataclass holds but the tuple omits is reported as unknown, and one the tuple lists
but no reader reads is accepted and then silently dropped.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Package:
    """The `DEBIAN/control` fields."""

    name: str
    version: str
    architecture: str
    maintainer: str
    description: str
    long_description: str | None
    section: str
    priority: str
    homepage: str | None
    depends: list[str]
    recommends: list[str]
    conflicts: list[str]
    replaces: list[str]


_PACKAGE_KEYS = (
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
)


@dataclass
class Install:
    """Where the package puts itself on the target."""

    prefix: str
    dir_name: str
    version_dir: str
    current_symlink: bool
    start_on_install: bool
    stop_on_remove: bool

    @property
    def root_dir(self) -> str:
        """`/opt/<pkg>` -- everything this package owns, and what `postrm purge` clears."""
        return f"{self.prefix}/{self.dir_name}"

    @property
    def target_dir(self) -> str:
        """`/opt/<pkg>/<version>` -- the directory dpkg replaces wholesale on upgrade."""
        return f"{self.root_dir}/{self.version_dir}"

    @property
    def current_dir(self) -> str:
        """`/opt/<pkg>/current` -- what the helpers resolve at call time, never a version."""
        return f"{self.root_dir}/current"


_INSTALL_KEYS = (
    "prefix",
    "dir_name",
    "version_dir",
    "current_symlink",
    "start_on_install",
    "stop_on_remove",
)


@dataclass
class Source:
    """Where the compose file and its neighbours come from.

    `path` means different things per kind: a subpath inside the repository for `git`, and
    the directory itself for `local` (relative paths resolve against the spec file).
    """

    kind: str
    url: str | None
    ref: str | None
    path: str
    insecure_tls: bool


_SOURCE_KEYS = ("kind", "url", "ref", "path", "insecure_tls")


@dataclass
class Env:
    """`.env` generation. `template` is None when the app ships no env file."""

    template: str | None
    output: str
    strict: bool
    vars: dict[str, str]


_ENV_KEYS = ("template", "output", "strict", "vars")


@dataclass
class Registry:
    host: str | None
    require_login: bool


_REGISTRY_KEYS = ("host", "require_login")


@dataclass
class Deployment:
    kind: str
    mode: str
    source: Source
    compose_files: list[str]
    extra_files: list[str]
    render_templates: list[str]
    env: Env
    registry: Registry
    images: list[str]
    remove_image_archive_after_load: bool


_DEPLOYMENT_KEYS = (
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
)


@dataclass
class Helpers:
    enabled: bool
    prefix: str
    commands: list[str]

    def command_names(self) -> list[str]:
        """The `/usr/bin` entries this package installs."""
        return [f"{self.prefix}-{command}" for command in self.commands]


_HELPERS_KEYS = ("enabled", "prefix", "commands")


@dataclass
class DesktopEntry:
    filename: str
    name: str
    comment: str | None
    exec: str
    icon: str | None
    terminal: bool
    categories: list[str]


_DESKTOP_ENTRY_KEYS = (
    "filename", "name", "comment", "exec", "icon", "terminal", "categories"
)


@dataclass
class ExtraFile:
    """A file copied from beside the spec to an absolute path on the target."""

    source: str
    dest: str
    mode: str


_EXTRA_FILE_KEYS = ("source", "dest", "mode")


@dataclass
class Hooks:
    """Shell fragments appended to the generated maintainer scripts."""

    postinst: str | None
    prerm: str | None
    postrm: str | None


_HOOKS_KEYS = ("postinst", "prerm", "postrm")


@dataclass
class Spec:
    schema_version: int
    package: Package
    install: Install
    deployment: Deployment
    helpers: Helpers
    desktop_entries: list[DesktopEntry]
    files: list[ExtraFile]
    hooks: Hooks
    spec_path: Path

    @property
    def directory(self) -> Path:
        """The folder holding the spec: `files[].source` and `hooks.*` resolve against it."""
        return self.spec_path.parent


#: Spelt out rather than taken from `Spec`, whose ninth field is `spec_path` -- where the
#: file was found, not something anyone writes in it.
_ROOT_KEYS = (
    "schema_version",
    "package",
    "install",
    "deployment",
    "helpers",
    "desktop_entries",
    "files",
    "hooks",
)
