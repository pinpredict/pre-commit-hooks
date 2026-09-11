#!/usr/bin/env python3
"""Assert a published k5s fragment agrees with how its own repo runs the service.

A repo that publishes a `kind: Fragment` is telling every other repo how to run
one of its services. It almost always runs that service itself too, from its own
stack — so there are two definitions of one thing in one repo, and nothing makes
them agree.

They drift immediately. magellan published a fragment pinning all seven collector
intervals to 60s; six minutes later a separate PR removed exactly those overrides
from the repo's own rig, for a measured reason (magellan#651, #652). Both landed
green. The fragment then told every consumer to do the thing the owner had just
decided not to do, and the only reason it was caught was a human reading both
files side by side while preparing an unrelated adoption.

That is the failure this hook exists for, and it is the same shape as every other
drift problem fragments were built to end — except it is *inside* the publishing
repo, where the fragment registry itself cannot help.

# What is compared

For each fragment service, the hook finds the corresponding service in the repo's
own stack files and compares:

  * **env values** — a key both sides set must set it to the same thing.
  * **one-sided keys** — a key only one side sets is reported, because that is
    how the interval drift looked: the fragment set seven keys the owner did not.

# What is NOT compared, and why

A value the fragment PARAMETERIZES cannot drift — `${input:dbHost}` is not a
claim about what the value should be, it is a statement that the caller decides.
Those are skipped entirely; comparing them would report every input as a
disagreement.

Keys that are legitimately different between an owner and a consumer are ignored
by default (`DEFAULT_IGNORE`): the owner builds from source while consumers pull
a released image, and placement/sizing belongs to whoever runs the rig. Extend it
with `--ignore` rather than weakening the value comparison.

Every assertion is opt-in on the surfaces being present, so a repo that publishes
no fragment is a clean no-op.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pinpredict_hooks._common import MISSING, emit as _emit, load_yaml as _load_yaml

PROG = "k5s-fragment-parity"

# The token a fragment uses to say "the caller decides this". A value containing
# one is a parameter, not a claim, so it is never a drift candidate.
INPUT_TOKEN = "${input:"

# Keys an owner and a consumer are EXPECTED to differ on.
#
# `build`/`image`/`tag` is the owner-vs-consumer split by design: the publishing
# repo builds from source, consumers pull a released image. The rest is placement
# and sizing, which belong to whoever is standing the rig up — a fragment that
# pinned them would be a one-way door, since stack overlays deep-merge and cannot
# delete a key.
DEFAULT_IGNORE = frozenset(
    {
        "build",
        "image",
        "tag",
        "namespace",
        "replicas",
        "resources",
        "expose",
        "readyTimeout",
        "dependsOn",
        "scheduling",
        "localPorts",
    }
)


def _is_fragment(doc: Any) -> bool:
    return isinstance(doc, dict) and doc.get("kind") == "Fragment"


def _services(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict):
        return {}
    services = doc.get("services")
    return services if isinstance(services, dict) else {}


def _env(service: Any) -> dict[str, Any]:
    if not isinstance(service, dict):
        return {}
    env = service.get("env")
    if isinstance(env, dict):
        return env
    # A list-form env (`- KEY=value`) is normalized so both spellings compare.
    if isinstance(env, list):
        out: dict[str, Any] = {}
        for item in env:
            if isinstance(item, str) and "=" in item:
                key, value = item.split("=", 1)
                out[key] = value
        return out
    return {}


def _parameterized(value: Any) -> bool:
    return INPUT_TOKEN in str(value)


def _as_env(value: Any) -> str:
    """Render a YAML scalar the way it reaches a container's environment.

    Env values are strings by schema, so `Enabled: false` and `Enabled: 'false'`
    are the same setting written two ways — but Python's str() renders the bool
    as 'False', so a naive comparison reports them as drift. trading's own
    fragment and overlay differ exactly that way, and it was the first thing this
    hook said about them.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _find_own(stacks: dict[Path, Any], want: str) -> list[Path]:
    """Every stack file in the repo that defines `want`.

    Deliberately returns ALL of them rather than picking one. A repo routinely
    defines a service in several lanes — a base plus overlays, or two parallel
    rigs — and they are SUPPOSED to differ: a lane's whole job is to override the
    base. Comparing a fragment against whichever file happened to sort first
    reports those deliberate overrides as drift, against a file nobody meant.

    That is not hypothetical: the first run of this hook against magellan
    compared `k5s/fragment.yaml` to `overlays/magellan-go.yaml` — a different
    lane entirely — because `-go` sorts before `.yaml`.

    So the caller decides, with --against. Ambiguity is an error, not a guess.
    """
    return [path for path in sorted(stacks) if want in _services(stacks[path])]


def check(
    fragments: dict[Path, Any],
    stacks: dict[Path, Any],
    mapping: dict[str, str],
    ignore: frozenset[str],
    report_one_sided: bool,
    explicit_against: bool,
) -> list[str]:
    failures: list[str] = []
    for frag_path in sorted(fragments):
        doc = fragments[frag_path]
        if not _is_fragment(doc):
            continue
        for frag_service, frag_body in sorted(_services(doc).items()):
            own_name = mapping.get(frag_service, frag_service)
            matches = _find_own(stacks, own_name)
            if not matches:
                # Not a failure: a repo may publish a fragment for something it
                # does not stand up itself. Saying so would make the hook noisy
                # in exactly the repos already doing the right thing.
                continue
            if len(matches) > 1 and not explicit_against:
                failures.append(
                    f"{frag_path} [{frag_service}]: service {own_name!r} is defined in "
                    f"{len(matches)} stack files ({', '.join(str(m) for m in matches)}) and "
                    f"they are supposed to differ — a lane overrides its base. Name the one "
                    f"the fragment mirrors with --against, rather than having this hook pick."
                )
                continue
            own_path = matches[0]
            own_body = _services(stacks[own_path])[own_name]

            frag_env, own_env = _env(frag_body), _env(own_body)
            where = f"{frag_path} [{frag_service}] vs {own_path} [{own_name}]"

            for key in sorted(set(frag_env) & set(own_env)):
                if key in ignore or _parameterized(frag_env[key]):
                    continue
                if _as_env(frag_env[key]) != _as_env(own_env[key]):
                    failures.append(
                        f"{where}: env {key} disagrees — "
                        f"fragment {frag_env[key]!r}, repo {own_env[key]!r}"
                    )

            if not report_one_sided:
                continue

            only_frag = {
                k for k in set(frag_env) - set(own_env)
                if k not in ignore and not _parameterized(frag_env[k])
            }
            for key in sorted(only_frag):
                failures.append(
                    f"{where}: the FRAGMENT sets env {key}={frag_env[key]!r} and this "
                    f"repo's own service does not — consumers get a value the owner "
                    f"decided against (pass --ignore {key} if that is deliberate)"
                )
            only_own = {k for k in set(own_env) - set(frag_env) if k not in ignore}
            for key in sorted(only_own):
                failures.append(
                    f"{where}: this repo sets env {key}={own_env[key]!r} and the "
                    f"fragment it publishes does not — consumers will not get it "
                    f"(pass --ignore {key} if that is deliberate)"
                )
    return failures


def _mapping(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"{PROG}: --service wants FRAGMENT_NAME=REPO_NAME, got {pair!r}")
        frag, own = pair.split("=", 1)
        out[frag.strip()] = own.strip()
    return out


def _load(paths: list[Path]) -> dict[Path, Any]:
    out: dict[Path, Any] = {}
    for path in paths:
        doc = _load_yaml(path, PROG)
        if doc is not MISSING:
            out[path] = doc
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--fragment", action="append", default=[])
    parser.add_argument("--against", action="append", default=[])
    parser.add_argument("--service", action="append", default=[])
    parser.add_argument("--ignore", action="append", default=[])
    parser.add_argument(
        "--no-one-sided",
        action="store_true",
        help="only fail when a shared key disagrees, not when one side sets a key alone",
    )
    parser.add_argument("filenames", nargs="*")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    frag_paths = [Path(p) for p in args.fragment]
    if not frag_paths:
        # Conventional locations: the single-fragment default path and the
        # directory a multi-service repo publishes into.
        frag_paths = [Path("k5s/fragment.yaml"), *sorted(Path("k5s/fragments").glob("*.y*ml"))]
    fragments = _load([p for p in frag_paths if p.exists()])
    if not fragments:
        return 0

    stack_paths = [Path(p) for p in args.against]
    if not stack_paths:
        stack_paths = [
            p
            for p in [Path("k5s.yaml"), *sorted(Path("overlays").glob("*.y*ml"))]
            if p.exists()
        ]
    stacks = _load(stack_paths)
    if not stacks:
        return 0

    failures = check(
        fragments,
        stacks,
        _mapping(args.service),
        DEFAULT_IGNORE | frozenset(args.ignore),
        report_one_sided=not args.no_one_sided,
        explicit_against=bool(args.against),
    )
    if failures:
        _emit(failures, PROG)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
