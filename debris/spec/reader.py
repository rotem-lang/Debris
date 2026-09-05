"""Typed access to one JSON object at a time, recording problems instead of raising.

A `_Reader` knows nothing about which section it holds. It answers "is this key a string,
a boolean, a list of relative paths?" and records a problem when it is not, returning None
for anything it rejected. That is what lets one `debris validate` collect a whole report
in a single pass, and it is why the loader refuses to hand back a Spec while any problem
is outstanding: only that refusal keeps the `str` annotations in `model.py` honest.
"""

import re
from typing import Any

from debris.spec.problems import _Problems
from debris.spec.values import _closest, _relative_path_problem

_MISSING = object()

# `DEBIAN/control`, `.desktop` files and `.env` are all line-oriented, so an embedded
# newline in any single-line value either corrupts the file or injects a field into it --
# and dpkg only notices on the target machine. `long_description` is the one value that is
# genuinely allowed to fold across lines.
_NEWLINE_COMPLAINT = (
    "must be a single line; a newline here would corrupt the file it is written into"
)


def _has_newline(value: str) -> bool:
    return "\n" in value or "\r" in value


_TYPE_NAMES = {
    type(None): "null",
    bool: "a boolean",
    int: "a number",
    float: "a number",
    str: "a string",
    list: "a list",
    dict: "an object",
}


def _kind_of(value: Any) -> str:
    return _TYPE_NAMES.get(type(value), type(value).__name__)


class _Reader:
    """Typed access to one JSON object, recording problems instead of raising.

    Accessors validate only values that were actually present in the file. Defaults come
    from the loader and are trusted, which is what stops a single missing key from
    producing a second, misleading complaint about the default that replaced it.

    A `quiet` reader stands in for a required object that was absent. It swallows problems,
    because everything it would report is a consequence of the one already recorded: a
    missing `deployment` should say so once, not also demand `deployment.source.url`.
    """

    def __init__(
            self,
            data: dict[str, Any],
            path: str,
            problems: _Problems,
            *,
            quiet: bool = False,
    ) -> None:
        self._data = data
        self._path = path
        self._problems = problems
        self._quiet = quiet

    def has(self, key: str) -> bool:
        return key in self._data

    def at(self, key: str) -> str:
        return f"{self._path}.{key}" if self._path else key

    def failed(self, key: str) -> bool:
        """Whether `key` was present but rejected, as opposed to absent."""
        return self.at(key) in self._problems.failed

    def problem(self, message: str, key: str | None = None) -> None:
        if self._quiet:
            return
        self._problems.add(self.at(key) if key else self._path or "<root>", message)

    def _raw(self, key: str, default: Any) -> tuple[Any, bool]:
        """Return `(value, present)`; `present` is False when `value` is a trusted default."""
        if key in self._data:
            return self._data[key], True
        if default is _MISSING:
            self.problem("required key is missing", key)
            return None, False
        return default, False

    def string(
            self,
            key: str,
            *,
            default: Any = _MISSING,
            pattern: re.Pattern[str] | None = None,
            expected: str | None = None,
            choices: tuple[str, ...] | None = None,
            nullable: bool = False,
            allow_empty: bool = False,
            allow_newlines: bool = False,
    ) -> str | None:
        value, present = self._raw(key, default)
        if not present:
            return value
        if value is None and nullable:
            return None
        if not isinstance(value, str):
            self.problem(f"expected a string, got {_kind_of(value)}", key)
            return None
        if not value.strip() and not allow_empty:
            self.problem("must not be empty", key)
            return None
        if not allow_newlines and _has_newline(value):
            self.problem(_NEWLINE_COMPLAINT, key)
            return None
        if choices is not None and value not in choices:
            self.problem(f"expected one of {', '.join(map(repr, choices))}, got {value!r}", key)
            return None
        if pattern is not None and not pattern.match(value):
            self.problem(f"{value!r} is not {expected}", key)
            return None
        return value

    def boolean(self, key: str, *, default: Any = _MISSING) -> bool | None:
        value, present = self._raw(key, default)
        if not present:
            return value
        if not isinstance(value, bool):
            self.problem(f"expected a boolean, got {_kind_of(value)}", key)
            return None
        return value

    def integer(self, key: str, *, default: Any = _MISSING) -> int | None:
        value, present = self._raw(key, default)
        if not present:
            return value
        if not isinstance(value, int) or isinstance(value, bool):
            self.problem(f"expected a number, got {_kind_of(value)}", key)
            return None
        return value

    def string_list(
            self,
            key: str,
            *,
            default: Any = _MISSING,
            choices: tuple[str, ...] | None = None,
            allow_empty: bool = True,
    ) -> list[str] | None:
        value, present = self._raw(key, default)
        if not present:
            return value
        if not isinstance(value, list):
            self.problem(f"expected a list of strings, got {_kind_of(value)}", key)
            return None
        if not value and not allow_empty:
            self.problem("must not be empty", key)
            return None
        items: list[str] = []
        for index, item in enumerate(value):
            where = f"{key}[{index}]"
            if not isinstance(item, str):
                self.problem(f"expected a string, got {_kind_of(item)}", where)
                continue
            if not item.strip():
                self.problem("must not be empty", where)
                continue
            if _has_newline(item):
                self.problem(_NEWLINE_COMPLAINT, where)
                continue
            if choices is not None and item not in choices:
                self.problem(
                    f"expected one of {', '.join(map(repr, choices))}, got {item!r}", where
                )
                continue
            items.append(item)
        return items

    def string_map(
            self,
            key: str,
            *,
            default: Any = _MISSING,
            key_pattern: re.Pattern[str] | None = None,
            key_expected: str | None = None,
    ) -> dict[str, str] | None:
        value, present = self._raw(key, default)
        if not present:
            return value
        if not isinstance(value, dict):
            self.problem(f"expected an object, got {_kind_of(value)}", key)
            return None
        items: dict[str, str] = {}
        for name, item in value.items():
            where = f"{key}.{name}"
            if key_pattern is not None and not key_pattern.match(name):
                self.problem(f"{name!r} is not {key_expected}", where)
                continue
            if not isinstance(item, str):
                # Numbers are the common slip here, and silently stringifying `true` or
                # `1.40` would put something surprising in `.env`.
                self.problem(
                    f"expected a string, got {_kind_of(item)}; quote the value, because "
                    "everything in a .env file is text",
                    where,
                )
                continue
            if _has_newline(item):
                self.problem(_NEWLINE_COMPLAINT, where)
                continue
            items[name] = item
        return items

    def relative_path(
            self,
            key: str,
            *,
            default: Any = _MISSING,
            nullable: bool = False,
            allow_empty: bool = False,
    ) -> str | None:
        """A path inside the fetched source tree."""
        value = self.string(
            key, default=default, nullable=nullable, allow_empty=allow_empty
        )
        if isinstance(value, str) and self.has(key):
            complaint = _relative_path_problem(value)
            if complaint:
                self.problem(complaint, key)
                return None
        return value

    def relative_path_list(
            self, key: str, *, default: Any = _MISSING, allow_empty: bool = True
    ) -> list[str] | None:
        values = self.string_list(key, default=default, allow_empty=allow_empty)
        if not self.has(key) or values is None:
            return values
        kept: list[str] = []
        for index, value in enumerate(values):
            complaint = _relative_path_problem(value)
            if complaint:
                self.problem(complaint, f"{key}[{index}]")
                continue
            kept.append(value)
        return kept

    def child(self, key: str, *, required: bool = False) -> "_Reader":
        """A nested object.

        An absent *optional* child reads as empty and takes its defaults. An absent or
        malformed *required* one reads as quiet, so `deployment: required key is missing`
        is not followed by four complaints about keys inside the section that isn't there.
        """
        if key not in self._data:
            if required:
                self.problem("required key is missing", key)
                return _Reader({}, self.at(key), self._problems, quiet=True)
            return _Reader({}, self.at(key), self._problems, quiet=self._quiet)
        value = self._data[key]
        if not isinstance(value, dict):
            self.problem(f"expected an object, got {_kind_of(value)}", key)
            return _Reader({}, self.at(key), self._problems, quiet=True)
        return _Reader(value, self.at(key), self._problems, quiet=self._quiet)

    def children(self, key: str) -> list["_Reader"]:
        """A list of nested objects, each addressed as `key[index]` in messages."""
        if key not in self._data:
            return []
        value = self._data[key]
        if not isinstance(value, list):
            self.problem(f"expected a list of objects, got {_kind_of(value)}", key)
            return []
        readers: list[_Reader] = []
        for index, item in enumerate(value):
            where = f"{self.at(key)}[{index}]"
            if not isinstance(item, dict):
                if not self._quiet:
                    self._problems.add(where, f"expected an object, got {_kind_of(item)}")
                continue
            readers.append(_Reader(item, where, self._problems, quiet=self._quiet))
        return readers

    def reject_unknown(self, *known: str) -> None:
        """Catch typo'd keys.

        A misspelt key is silently ignored otherwise, and the mistake only shows up as a
        missing feature on the target machine.
        """
        for key in sorted(set(self._data) - set(known)):
            suggestion = _closest(key, known)
            hint = f"; did you mean {suggestion!r}?" if suggestion else ""
            self.problem(f"unknown key{hint}", key)
