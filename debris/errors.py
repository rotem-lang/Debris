"""Exception types shared across Debris.

Everything Debris raises deliberately derives from `DebrisError` so the CLI can turn
expected failures into a clean message and a non-zero exit code, while genuine bugs still
surface as tracebacks.
"""


class DebrisError(Exception):
    """Base class for every error Debris reports to the user."""


class SpecError(DebrisError):
    """The JSON spec is missing, malformed, or fails validation."""


class SourceError(DebrisError):
    """Fetching the app's compose files from git or a local path failed."""


class RenderError(DebrisError):
    """Rendering a template failed, typically an unresolved ${VAR} placeholder."""


class BuildError(DebrisError):
    """Staging the package tree or invoking dpkg-deb failed."""


class ToolError(DebrisError):
    """A required external tool (git, docker, dpkg-deb) is missing or returned an error."""
