"""One reader per spec section: JSON in, a dataclass out.

A section reader is the only place that knows both a section's defaults and its per-key
rules, which is why the defaults are not repeated on the dataclasses. Rules that need more
than one section live in `crosscheck.py` and run after every section has been read: a
section reader reaching across to another would be reading values that do not exist yet.
"""

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
    _DEPLOYMENT_KEYS,
    _DESKTOP_ENTRY_KEYS,
    _ENV_KEYS,
    _EXTRA_FILE_KEYS,
    _HELPERS_KEYS,
    _HOOKS_KEYS,
    _INSTALL_KEYS,
    _PACKAGE_KEYS,
    _REGISTRY_KEYS,
    _SOURCE_KEYS,
)
from debris.spec.patterns import (
    BACKEND_KINDS,
    ENV_KEY,
    ENV_KEY_EXPECTED,
    HELPER_COMMANDS,
    MODES,
    PACKAGE_NAME,
    PACKAGE_NAME_EXPECTED,
    SOURCE_KINDS,
    _ABSOLUTE_PATH,
    _ARCHITECTURE,
    _DESKTOP_FILENAME,
    _FILE_MODE,
    _FILE_MODE_EXPECTED,
    _MAINTAINER,
    _PATH_SEGMENT,
    _PRIORITIES,
    _REGISTRY_HOST,
    _VERSION,
    _VERSION_EXPECTED,
)
from debris.spec.reader import _Reader, _has_newline
from debris.spec.values import _dotdot_problem, _image_problem


def _read_package(reader: _Reader) -> Package:
    package = Package(
        name=reader.string("name", pattern=PACKAGE_NAME, expected=PACKAGE_NAME_EXPECTED),
        version=reader.string("version", pattern=_VERSION, expected=_VERSION_EXPECTED),
        architecture=reader.string(
            "architecture",
            default="all",
            pattern=_ARCHITECTURE,
            expected="a Debian architecture such as 'all', 'amd64' or 'arm64'",
        ),
        maintainer=reader.string(
            "maintainer", pattern=_MAINTAINER, expected="'Name <email@host>'"
        ),
        # Read with newlines allowed so the check below can give the useful message rather
        # than the generic one; a multi-line synopsis is still rejected.
        description=reader.string("description", allow_newlines=True),
        long_description=reader.string(
            "long_description", default=None, nullable=True, allow_newlines=True
        ),
        section=reader.string("section", default="misc"),
        priority=reader.string("priority", default="optional", choices=_PRIORITIES),
        homepage=reader.string("homepage", default=None, nullable=True),
        depends=reader.string_list("depends", default=[]),
        recommends=reader.string_list("recommends", default=[]),
        conflicts=reader.string_list("conflicts", default=[]),
        replaces=reader.string_list("replaces", default=[]),
    )
    if package.description and _has_newline(package.description):
        # `Description:` is a one-line synopsis; the rest belongs in the folded continuation.
        reader.problem(
            "must be a single line; put the rest in 'long_description'", "description"
        )
    reader.reject_unknown(*_PACKAGE_KEYS)
    return package


def _read_install(reader: _Reader, package: Package) -> Install:
    install = Install(
        prefix=reader.string(
            "prefix", default="/opt", pattern=_ABSOLUTE_PATH, expected="an absolute path"
        ),
        dir_name=reader.string(
            "dir_name",
            default=package.name,
            pattern=PACKAGE_NAME,
            expected=PACKAGE_NAME_EXPECTED,
        ),
        version_dir=reader.string(
            "version_dir",
            default=package.version,
            pattern=_PATH_SEGMENT,
            expected="a single path segment",
        ),
        current_symlink=reader.boolean("current_symlink", default=True),
        start_on_install=reader.boolean("start_on_install", default=False),
        stop_on_remove=reader.boolean("stop_on_remove", default=True),
    )
    if install.version_dir in (".", ".."):
        reader.problem(f"{install.version_dir!r} is not a usable directory name", "version_dir")
    if install.prefix and reader.has("prefix"):
        complaint = _dotdot_problem(install.prefix)
        if complaint:
            reader.problem(complaint, "prefix")
    reader.reject_unknown(*_INSTALL_KEYS)
    return install


def _read_deployment(reader: _Reader, mode_override: str | None) -> Deployment:
    # Read before the dataclass rather than inside it: the file's own `mode` is validated
    # even when overridden, and reading it first keeps it ahead of `kind` in the report.
    mode = _resolve_mode(reader, mode_override)

    deployment = Deployment(
        kind=reader.string("kind", default="compose", choices=BACKEND_KINDS),
        mode=mode,
        source=_read_source(reader.child("source", required=True)),
        compose_files=reader.relative_path_list(
            "compose_files", default=["docker-compose.yml"], allow_empty=False
        ),
        extra_files=reader.relative_path_list("extra_files", default=[]),
        render_templates=reader.relative_path_list("render_templates", default=[]),
        env=_read_env(reader.child("env")),
        registry=_read_registry(reader.child("registry")),
        images=reader.string_list("images", default=[]),
        remove_image_archive_after_load=reader.boolean(
            "remove_image_archive_after_load", default=False
        ),
    )
    _check_images(reader, deployment.images)
    reader.reject_unknown(*_DEPLOYMENT_KEYS)
    return deployment


def _resolve_mode(reader: _Reader, mode_override: str | None) -> str:
    """The mode the build will use: `--mode` when it was given, the file's value otherwise.

    Offline is the default because the closed network is the normal case; `online` is the
    deliberate opt-in for sites whose internal registry is reachable at install time. The
    file's own value is read even when overridden, so passing `--mode` cannot hide a spec
    that `validate` would have rejected.
    """
    declared = reader.string("mode", default="offline", choices=MODES)
    return mode_override or declared


def _check_images(reader: _Reader, images: list[str] | None) -> None:
    """Complain about every unusable reference, not just the first one in the list."""
    for index, image in enumerate(images or []):
        complaint = _image_problem(image)
        if complaint:
            reader.problem(complaint, f"images[{index}]")


def _read_source(reader: _Reader) -> Source:
    kind = reader.string("kind", default="git", choices=SOURCE_KINDS)
    if kind is None:
        # The kind was present but rejected. Guessing which branch was meant would demand
        # `url` and `ref` from someone who wrote "Local", so read nothing further.
        reader.reject_unknown(*_SOURCE_KEYS)
        return Source(kind="git", url=None, ref=None, path="", insecure_tls=False)
    if kind == "local":
        # A local checkout has no URL to clone and no ref to pin; accepting those keys
        # silently would hide a spec that was half-converted from git.
        for unused in ("url", "ref", "insecure_tls"):
            if reader.has(unused):
                reader.problem('is not used when source.kind is "local"', unused)
        source = Source(
            kind=kind,
            url=None,
            ref=None,
            path=reader.string("path"),
            insecure_tls=False,
        )
    else:
        source = Source(
            kind=kind or "git",
            url=reader.string("url"),
            ref=reader.string("ref"),
            path=reader.relative_path("path", default="", allow_empty=True),
            insecure_tls=reader.boolean("insecure_tls", default=False),
        )
    reader.reject_unknown(*_SOURCE_KEYS)
    return source


def _read_env(reader: _Reader) -> Env:
    # `template` defaults to None rather than '.env.template': assuming a template exists
    # would break every app that ships no env file, and the failure would only appear when
    # the fetch could not find it.
    env = Env(
        template=reader.relative_path("template", default=None, nullable=True),
        output=reader.relative_path("output", default=".env"),
        strict=reader.boolean("strict", default=True),
        vars=reader.string_map(
            "vars", default={}, key_pattern=ENV_KEY, key_expected=ENV_KEY_EXPECTED
        ),
    )
    reader.reject_unknown(*_ENV_KEYS)
    return env


def _read_registry(reader: _Reader) -> Registry:
    registry = Registry(
        host=reader.string(
            "host",
            default=None,
            nullable=True,
            pattern=_REGISTRY_HOST,
            expected="a registry host such as 'registry.corp.local:5000'",
        ),
        require_login=reader.boolean("require_login", default=False),
    )
    if registry.host and ":" in registry.host:
        # The pattern can only count the digits, so the range is checked here. Splitting
        # rather than capturing keeps the regex identical to the one in the editor schema,
        # which cannot express named groups.
        port = registry.host.rpartition(":")[2]
        if not 1 <= int(port) <= 65535:
            reader.problem(f"{port!r} is not a port number between 1 and 65535", "host")
    reader.reject_unknown(*_REGISTRY_KEYS)
    return registry


def _read_helpers(reader: _Reader, package: Package) -> Helpers:
    helpers = Helpers(
        enabled=reader.boolean("enabled", default=True),
        prefix=reader.string(
            "prefix",
            default=package.name,
            pattern=PACKAGE_NAME,
            expected=PACKAGE_NAME_EXPECTED,
        ),
        commands=reader.string_list(
            "commands", default=list(HELPER_COMMANDS), choices=HELPER_COMMANDS
        ),
    )
    reader.reject_unknown(*_HELPERS_KEYS)
    return helpers


def _read_desktop_entry(reader: _Reader) -> DesktopEntry:
    entry = DesktopEntry(
        filename=reader.string(
            "filename",
            pattern=_DESKTOP_FILENAME,
            expected="a file name ending in '.desktop'",
        ),
        name=reader.string("name"),
        comment=reader.string("comment", default=None, nullable=True),
        exec=reader.string("exec"),
        icon=reader.string("icon", default=None, nullable=True),
        terminal=reader.boolean("terminal", default=False),
        categories=reader.string_list("categories", default=[]),
    )
    reader.reject_unknown(*_DESKTOP_ENTRY_KEYS)
    return entry


def _read_file(reader: _Reader) -> ExtraFile:
    extra = ExtraFile(
        source=reader.relative_path("source"),
        dest=reader.string("dest", pattern=_ABSOLUTE_PATH, expected="an absolute path"),
        mode=reader.string(
            "mode", default="0644", pattern=_FILE_MODE, expected=_FILE_MODE_EXPECTED
        ),
    )
    if extra.dest:
        complaint = _dotdot_problem(extra.dest)
        if complaint:
            reader.problem(complaint, "dest")
    reader.reject_unknown(*_EXTRA_FILE_KEYS)
    return extra


def _read_hooks(reader: _Reader) -> Hooks:
    hooks = Hooks(
        postinst=reader.relative_path("postinst", default=None, nullable=True),
        prerm=reader.relative_path("prerm", default=None, nullable=True),
        postrm=reader.relative_path("postrm", default=None, nullable=True),
    )
    reader.reject_unknown(*_HOOKS_KEYS)
    return hooks
