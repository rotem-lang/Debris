"""Rules about one value, independent of the key it arrived under.

Each function answers a single question -- why is this value unusable? -- and returns the
sentence to report, or None. They live apart from the readers so that tightening the image
or path rules does not mean reading the section layout, and so that the readers stay about
types and presence rather than about what a docker reference may contain.
"""

import difflib
import re
from pathlib import PurePosixPath


def _closest(key: str, known: tuple[str, ...]) -> str | None:
    """The nearest known key, when one is close enough to be worth suggesting."""
    matches = difflib.get_close_matches(key, known, n=1, cutoff=0.75)
    return matches[0] if matches else None


def _dotdot_problem(value: str) -> str | None:
    """Why an absolute destination is unsafe to stage, or None.

    `_ABSOLUTE_PATH` accepts '..' as an ordinary segment, but dpkg records the literal path
    it is given, so a `dest` of '/usr/share/../../etc/passwd' would stage outside the tree.
    """
    if ".." in PurePosixPath(value).parts:
        return f"{value!r} must not contain '..'"
    return None


def _relative_path_problem(value: str) -> str | None:
    """Why `value` cannot be used as a path inside a fetched source tree, or None."""
    if value.startswith("/"):
        return f"{value!r} must be relative to the source directory, not absolute"
    parts = PurePosixPath(value).parts
    if ".." in parts:
        return f"{value!r} must not contain '..'"
    if "\\" in value:
        return f"{value!r} must use '/' as the path separator"
    return None


#: A docker path component: lowercase alphanumerics, with single separators between them.
_IMAGE_COMPONENT = re.compile(r"[a-z0-9]+([._-][a-z0-9]+)*\Z")
_IMAGE_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}\Z")


def _image_problem(ref: str) -> str | None:
    """Why `ref` is not a safely resolvable image reference, or None.

    Docker rejects these too, but it does so during `docker pull` on the build host, after
    the fetch and render have already run. Catching them here keeps the failure next to the
    line of the spec that caused it.
    """
    if any(character.isspace() for character in ref):
        return f"{ref!r} must not contain whitespace"
    name, complaint = _split_reference(ref)
    return complaint or _repository_problem(ref, name)


def _split_reference(ref: str) -> tuple[str, str | None]:
    """The repository part of `ref`, and why its digest or tag is unusable, or None.

    The name is only meaningful when the complaint is None. A tag lives after the last
    colon of the final path component, so the trailing component is peeled off first; a
    colon earlier in the reference is the registry's port.
    """
    if "@" in ref:
        name, _, digest = ref.partition("@")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            return name, (
                f"{ref!r} has a digest that is not 'sha256:' followed by 64 hex characters"
            )
        return name, None

    head, _, last = ref.rpartition("/")
    prefix, separator, tag = last.partition(":")
    if not separator:
        return ref, (
            f"{ref!r} must name an explicit tag or digest; an untagged reference means "
            "':latest', which is not reproducible and may not exist in the internal "
            "registry"
        )
    if not _IMAGE_TAG.match(tag):
        return ref, f"{ref!r} has a tag docker will not accept: {tag!r}"
    name = f"{head}/{prefix}" if head else prefix
    return name, None


def _repository_problem(ref: str, name: str) -> str | None:
    """Why the repository part of `ref` is not one docker will accept, or None.

    `name` is `ref` with the tag or digest already peeled off. Both are needed: the check
    is on the name, but the message quotes the reference the spec actually contains.
    """
    components = name.split("/")
    # A leading component with a dot, a colon, or the literal 'localhost' is the registry,
    # which follows host rules rather than repository rules.
    if len(components) > 1 and ("." in components[0] or ":" in components[0]):
        components = components[1:]
    elif len(components) > 1 and components[0] == "localhost":
        components = components[1:]

    for component in components:
        if not _IMAGE_COMPONENT.match(component):
            return (
                f"{ref!r} has a repository component docker will not accept: "
                f"{component!r} (lowercase letters, digits, and single '.', '_' or '-' "
                "between them)"
            )
    return None
