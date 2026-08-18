#!/usr/bin/env python3
"""Assert that sibling k5s stack overlays do not share a namespace.

A k5s rig is a base stack plus lane overlays (`k5s up -f overlays/perf-10x.yaml`).
Each lane that targets a shared cluster declares its own `namespace:` so that
bringing one lane up cannot converge the rig another lane is standing in.

That is easy to get wrong in exactly one way, and the way is quiet. A new lane
starts life as a copy of an existing one; if its `namespace:` is not changed with
everything else, `k5s up` on the new lane server-side-applies over the old lane's
objects. Nothing errors. The pods are Ready, the rig looks healthy, and it is
running a blend of two lanes' configuration — for a perf rig, that means every
number it reports is measured against a universe no one described.

Generic on purpose: it asserts uniqueness, never a naming convention. A repo's
lane names are its own business, and a hook that pinned `perf-rig-<lane>` would
be one repo's convention wearing an org hook's clothes.

A runtime suffix does not remove the need for this. k5s can append a per-engineer
suffix (`namespaceSuffix: user`), which separates PEOPLE — but two lanes declaring
the same base still resolve to the same namespace for any one engineer, so the
declared values must be distinct regardless. The two mechanisms cover different
axes and neither substitutes for the other.

Overlays that declare NO namespace are skipped, not flagged: inheriting the base
stack's namespace is the normal shape for a lane that only adjusts load, and it
is `k5s down`-safe because there is only ever one such rig.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from ._common import MISSING, emit, load_yaml

PROG = "k5s-stack-namespaces"


def namespace_of(path: Path) -> str | None:
    """Return the `namespace:` a stack file declares, or None.

    Reads the file as written — deliberately NOT through k5s's merge or
    `extends:` resolution. Two overlays that resolve to the same namespace only
    because they share a fragment are the case this must catch, and resolving
    first would hide it.
    """
    doc = load_yaml(path, PROG)
    if doc is MISSING or not isinstance(doc, dict):
        return None
    ns = doc.get("namespace")
    return ns if isinstance(ns, str) and ns else None


def check(paths: list[Path]) -> list[str]:
    """Group the given stacks by declared namespace and report any collision."""
    by_namespace: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(set(paths)):
        ns = namespace_of(path)
        if ns is not None:
            by_namespace[ns].append(path)

    failures = []
    for ns, owners in sorted(by_namespace.items()):
        if len(owners) > 1:
            listed = ", ".join(str(p) for p in owners)
            failures.append(
                f"namespace {ns!r} is declared by {len(owners)} stacks ({listed}) — "
                f"`k5s up` on one would server-side-apply over the other's objects "
                f"with no error, leaving a rig that blends both configurations. "
                f"Give each its own namespace."
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    # Defaulted so setuptools can wire this as a console script while a direct
    # `python -m` invocation still works.
    if argv is None:
        argv = sys.argv[1:]

    # pre-commit passes only the CHANGED files, but a collision is a property of
    # the whole SET — a lane whose namespace was already taken is invisible if the
    # file that took it is not in this commit. So the changed files only tell us
    # which directories to look at; every stack in those directories is compared.
    changed = [Path(a) for a in argv]
    if not changed:
        return 0
    scope: set[Path] = set()
    for path in changed:
        for sibling in path.parent.glob("*.y*ml"):
            if sibling.is_file():
                scope.add(sibling)

    failures = check(sorted(scope))
    if failures:
        emit(failures, PROG)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
