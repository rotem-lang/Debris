"""Accumulation of validation problems, kept apart from anything that reports them.

Validation reports every problem at once rather than the first, because a round trip to a
closed-network machine is expensive and one `debris validate` has to be enough to fix the
whole file. Collecting is all this module does; the loader decides when to raise and how
the list is formatted.
"""


class _Problems:
    """Collected problems, and the paths that produced them.

    `failed` is what lets a cross-field check tell "the key was absent" from "the key was
    there but rejected". Without it, a bad `deployment.env.template` draws both a complaint
    about the path and a second, untrue one saying no template is set.
    """

    def __init__(self) -> None:
        self.items: list[str] = []
        self.failed: set[str] = set()

    def add(self, path: str, message: str) -> None:
        self.items.append(f"{path}: {message}")
        self.failed.add(path)

    def __bool__(self) -> bool:
        return bool(self.items)

    def __len__(self) -> int:
        return len(self.items)
