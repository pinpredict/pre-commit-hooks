#!/usr/bin/env python3
"""Assert a repo's stevedore release-scope contract.

Onboarding or retiring a service must not silently widen the image build
contract so that *every* image in the catalog re-releases. This hook checks the
three surfaces where that widening happens:

  1. **Catalog/chart pairing** — a named service is an image id in
     `.stevedore.yaml` and has a sibling chart whose `Chart.yaml` name matches.
     Keeps a manual `services: <id>` dispatch resolvable on both release paths.

  2. **Release selectors** — the `docker-release` and `chart-release` reusable
     workflow calls receive the *same* `only:` selector, so a manual dispatch
     can never release a different set of images than charts.

  3. **`shared_paths` hygiene** — `change_detection.shared_paths` carries the
     explicit all-image contract signal, and does *not* carry paths that every
     service onboarding touches anyway (the Dockerfile, `.dockerignore`, the
     solution file). Listing those makes each onboarding rebuild the catalog.

Every assertion is opt-in via flags, so the hook fits repos that have only some
of these surfaces — a repo with no `chart-release` job or no `shared_paths` key
simply skips those checks rather than failing.

Unlike a fail-fast shell guard, all violations are collected and reported in a
single run, so one `pre-commit` invocation shows the whole picture.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml

MISSING = object()


def load_yaml(path: Path) -> Any:
    """Parse `path`, returning MISSING when the file does not exist."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return MISSING
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise SystemExit(f"stevedore-release-scope: {path} is not valid YAML: {error}")


def image_ids(catalog: Any) -> list[str]:
    images = (catalog or {}).get("images") or []
    return [image.get("id") for image in images if isinstance(image, dict)]


def shared_paths(catalog: Any) -> list[str] | None:
    """The declared shared_paths list, or None when the key is absent."""
    detection = (catalog or {}).get("change_detection")
    if not isinstance(detection, dict) or "shared_paths" not in detection:
        return None
    return list(detection.get("shared_paths") or [])


def check_services(
    catalog: Any, charts_dir: Path, services: list[str], failures: list[str]
) -> None:
    known = image_ids(catalog)
    for service in services:
        if service not in known:
            failures.append(
                f"{service!r} is not an image id in the stevedore catalog "
                f"(found: {', '.join(sorted(i for i in known if i)) or 'none'})"
            )

        chart = charts_dir / service / "Chart.yaml"
        doc = load_yaml(chart)
        if doc is MISSING:
            failures.append(f"{service!r} has no sibling chart at {chart}")
        elif not isinstance(doc, dict) or doc.get("name") != service:
            declared = doc.get("name") if isinstance(doc, dict) else None
            failures.append(
                f"{chart} declares name {declared!r} but must match the image id {service!r}"
            )


def check_shared_paths(
    catalog: Any, required: list[str], forbidden: list[str], failures: list[str]
) -> None:
    if not required and not forbidden:
        return

    declared = shared_paths(catalog)
    if declared is None:
        if required:
            failures.append(
                "change_detection.shared_paths is absent but "
                f"{', '.join(repr(path) for path in required)} must be declared"
            )
        # Nothing declared means nothing forbidden can be present.
        return

    for path in required:
        if path not in declared:
            failures.append(
                f"change_detection.shared_paths must contain {path!r} — it is the "
                "explicit all-image build-contract signal"
            )
    for path in forbidden:
        if path in declared:
            failures.append(
                f"change_detection.shared_paths must not contain {path!r} — every service "
                "onboarding touches it, so listing it re-releases the whole catalog"
            )


def check_selectors(
    workflow: Any,
    docker_job: str,
    chart_job: str,
    expected: str | None,
    failures: list[str],
) -> None:
    jobs = (workflow or {}).get("jobs")
    if not isinstance(jobs, dict):
        return

    found: dict[str, str] = {}
    for name in (docker_job, chart_job):
        job = jobs.get(name)
        if not isinstance(job, dict):
            continue
        with_block = job.get("with")
        found[name] = (with_block or {}).get("only", "") if isinstance(with_block, dict) else ""

    if not found:
        return

    if expected is not None:
        for name, selector in found.items():
            if selector != expected:
                failures.append(
                    f"job {name!r} passes only={selector!r} but the expected manual "
                    f"services selector is {expected!r}"
                )

    if len(found) == 2:
        (first_name, first), (second_name, second) = found.items()
        if first != second:
            failures.append(
                f"job {first_name!r} and job {second_name!r} pass different release "
                f"selectors ({first!r} vs {second!r}) — a manual dispatch would "
                "release a different set of images than charts"
            )


def emit(failures: list[str]) -> None:
    github = os.environ.get("GITHUB_ACTIONS") == "true"
    for failure in failures:
        prefix = "::error::" if github else "ERROR: "
        print(f"{prefix}stevedore release scope: {failure}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stevedore-release-scope", description=__doc__ or "", allow_abbrev=False
    )
    parser.add_argument("--catalog", default=".stevedore.yaml", type=Path)
    parser.add_argument("--workflow", default=".github/workflows/ci.yml", type=Path)
    parser.add_argument("--charts-dir", default="charts", type=Path)
    parser.add_argument(
        "--service",
        action="append",
        default=[],
        metavar="ID",
        help="assert this image id exists and has a name-matching sibling chart (repeatable)",
    )
    parser.add_argument(
        "--require-shared-path",
        action="append",
        default=[],
        metavar="PATH",
        help="assert change_detection.shared_paths contains PATH (repeatable)",
    )
    parser.add_argument(
        "--forbid-shared-path",
        action="append",
        default=[],
        metavar="PATH",
        help="assert change_detection.shared_paths does not contain PATH (repeatable)",
    )
    parser.add_argument(
        "--expect-selector",
        default=None,
        metavar="EXPR",
        help="assert both release jobs pass exactly this `only:` expression",
    )
    parser.add_argument("--docker-job", default="docker-release")
    parser.add_argument("--chart-job", default="chart-release")
    # pre-commit passes matched filenames even with pass_filenames: false in
    # some configurations; accept and ignore them so the hook stays robust.
    parser.add_argument("filenames", nargs="*", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    catalog = load_yaml(args.catalog)
    if catalog is MISSING:
        print(f"stevedore-release-scope: no {args.catalog}; nothing to check.")
        return 0

    failures: list[str] = []
    check_services(catalog, args.charts_dir, args.service, failures)
    check_shared_paths(catalog, args.require_shared_path, args.forbid_shared_path, failures)

    workflow = load_yaml(args.workflow)
    if workflow is not MISSING:
        check_selectors(
            workflow, args.docker_job, args.chart_job, args.expect_selector, failures
        )

    if failures:
        emit(failures)
        print(
            f"\n{len(failures)} release-scope violation(s). "
            "Onboarding must not widen the shared image build contract.",
            file=sys.stderr,
        )
        return 1

    checked = ", ".join(args.service) or "catalog"
    print(f"stevedore release scope OK ({checked}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
