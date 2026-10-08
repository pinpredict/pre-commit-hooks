#!/usr/bin/env python3
"""Reject a Kafka topic name in a service spec that breaks the org convention.

The convention is platform-gitops `docs/design/kafka-topic-naming.md`:

    pinpredict.<domain>.<subject>[.<subject>].<kind>.v<n>

It was written in 2026-08 and nothing enforced it. New topics kept arriving in
the old shapes (`pp-parlay-combo-leans`, `pp-rfq-fills`, `oms.exposure.v1`), each
created after the convention existed, at roughly one every twelve days. A doc
nobody has to read does not change what gets merged; a red pre-commit does.

Names are born and granted in `.platform/services/<svc>.yaml`, and every real
topic passes through one of those fields (it must be provisioned or granted to
be used at all), so that file is the one place a check covers everything. Topic
constants in application code are deliberately NOT scanned — see the design
doc's *Enforcement* section.

Why this is a hook and not the schema pattern the design doc describes: the
`.platform/services/.schema.json` copies are hand-vendored per repo in four
different versions and validate in only three repos, and the chart-side schema
in platform-gitops reaches prd on merge with no soak. A shared hook is one
implementation that every repo picks up by a `rev:` bump, and a mistake in it
fails a commit rather than an Argo render.

Existing non-conforming names are grandfathered in `kafka_legacy_topics.py`.
That list only ever SHRINKS: a rename removes the old name once nothing uses it.
Adding a name to it to get a new topic past this hook defeats the hook.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Iterator

from ._common import MISSING, emit, load_yaml
from .kafka_legacy_topics import LEGACY_TOPICS

PROG = "kafka-topic-names"

DOC = (
    "https://github.com/pinpredict/platform-gitops/blob/main/"
    "docs/design/kafka-topic-naming.md"
)

# The topic-bearing fields of a service spec. `groups` and `transactionalIds`
# share the grant arrays' schema pattern but are NOT topics — `oms-*` and
# `oms-emitter-nadex` are correct as they are — so they are left out on purpose.
GRANT_KEYS = frozenset(
    {"topics", "readTopics", "writeTopics", "adminTopics", "configReadTopics"}
)
PROVISION_KEY = "provisionTopics"

# Both registries are CLOSED: adding an entry is a PR against the design doc and
# then here, never a judgment call at topic-creation time.
DOMAINS = frozenset(
    {
        "oms", "trades", "rfq", "parlay", "controls", "fixtures", "md", "venue",
        "nadex", "kalshi", "rothera", "polymarket", "dkex", "pinnacle", "dis",
        "mag", "gamestate", "tt",
    }
)
KINDS = frozenset({"events", "commands", "state", "snapshot", "log"})

SEGMENT = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
VERSION = re.compile(r"^v[1-9][0-9]*$")
INFRA = re.compile(r"^__[a-z0-9]+(-[a-z0-9]+)*$")


def _segment_problems(segments: list[str]) -> list[str]:
    problems = []
    for seg in segments:
        if "_" in seg:
            problems.append(
                f"segment {seg!r} contains `_` — Kafka treats `.` and `_` as "
                f"colliding characters; use `-` inside a segment"
            )
        elif not SEGMENT.match(seg):
            problems.append(
                f"segment {seg!r} must be lowercase `[a-z0-9]` with `-` between words"
            )
    return problems


def problems_with(name: str, *, wildcard_ok: bool) -> list[str]:
    """Return why `name` breaks the convention; empty when it conforms."""
    if name in LEGACY_TOPICS:
        return []
    if name.startswith("__"):
        if INFRA.match(name):
            return []
        return ["an infra-internal name is `__<tool>-<purpose>`, lowercase"]

    if "*" in name:
        if not wildcard_ok:
            return ["a provisioned topic cannot contain `*`"]
        # A prefix grant: `pinpredict.<domain>.[<subject>.]*`. A bare `*` grants
        # every topic on the cluster and is not a prefix of anything.
        if not name.endswith(".*") or "*" in name[:-1]:
            return ["a wildcard grant must be a dotted prefix ending in `.*`"]
        prefix = name[:-2].split(".")
        problems = _segment_problems(prefix)
        if prefix[0] != "pinpredict" or len(prefix) < 2:
            problems.append("a prefix grant must start `pinpredict.<domain>.`")
        elif prefix[1] not in DOMAINS:
            problems.append(f"domain {prefix[1]!r} is not in the domain registry")
        return problems

    segments = name.split(".")
    if not 4 <= len(segments) <= 6:
        return [
            f"has {len(segments)} dot-separated segment(s); the shape is "
            f"`pinpredict.<domain>.<subject>[.<subject>].<kind>.v<n>` (4-6 segments)"
        ]
    problems = _segment_problems(segments)
    if segments[0] != "pinpredict":
        problems.append("the first segment must be the literal `pinpredict`")
    if segments[1] not in DOMAINS:
        problems.append(
            f"domain {segments[1]!r} is not in the domain registry "
            f"({', '.join(sorted(DOMAINS))}); the domain is the bounded context, "
            f"never the service name"
        )
    if not VERSION.match(segments[-1]):
        problems.append(f"must end in a version segment `v<n>`, not {segments[-1]!r}")

    # Between the domain and the version: 1-2 subjects plus an optional kind, at
    # most one of the two elided. The kind registry is closed so that the
    # second-to-last segment parses unambiguously; that only holds if no
    # subject is itself a kind word (hard rule 7).
    middle = segments[2:-1]
    for seg in middle[:-1]:
        if seg in KINDS:
            problems.append(
                f"subject segment {seg!r} is a kind word; a kind may only be "
                f"the second-to-last segment"
            )
    if len(middle) == 3 and middle[-1] not in KINDS:
        problems.append(
            f"three segments between domain and version need a kind last "
            f"({', '.join(sorted(KINDS))}), not {middle[-1]!r}"
        )
    return problems


def topic_names(node: Any, path: str = "") -> Iterator[tuple[str, str, bool]]:
    """Yield `(yaml-path, name, wildcard_ok)` for every topic in a spec.

    Walks the whole document rather than a known schema path: grants sit under
    `podIdentity.permissions.msk` today, and a field that moves must not leave
    its names unchecked.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if key in GRANT_KEYS and isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, str):
                        yield f"{here}[{i}]", item, True
            elif key == PROVISION_KEY and isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict) and isinstance(item.get("name"), str):
                        yield f"{here}[{i}].name", item["name"], False
            else:
                yield from topic_names(value, here)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from topic_names(item, f"{path}[{i}]")


def check(paths: list[Path]) -> list[str]:
    failures = []
    for path in sorted(set(paths)):
        doc = load_yaml(path, PROG)
        if doc is MISSING:
            continue
        for where, name, wildcard_ok in topic_names(doc):
            problems = problems_with(name, wildcard_ok=wildcard_ok)
            if problems:
                failures.append(
                    f"{path}: {where}: {name!r} does not follow the topic naming "
                    f"convention — {'; '.join(problems)}. See {DOC}"
                )
    return failures


def main(argv: list[str] | None = None) -> int:
    # Defaulted so setuptools can wire this as a console script while a direct
    # `python -m` invocation still works.
    if argv is None:
        argv = sys.argv[1:]
    failures = check([Path(a) for a in argv])
    if failures:
        emit(failures, PROG)
        print(
            f"{PROG}: an existing topic that predates the convention belongs in "
            f"pinpredict_hooks/kafka_legacy_topics.py in pinpredict/pre-commit-hooks; "
            f"a NEW topic must be named to the convention instead."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
