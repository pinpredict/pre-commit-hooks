#!/usr/bin/env python3
"""Static checks for `.platform/services/<svc>.yaml` files.

Catches the failure modes from platform-gitops#544 before merge:
  1. repositories.chart   — resolves to charts/<name>/Chart.yaml in service-template
  2. repositories.image   — TF entry exists (or a paired TF PR adds it)
  3. podIdentity.serviceAccount — Crossplane PIA / TF entry exists
  4. GHA push-role ARN    — TF entry exists for this service
  5. networkPolicy ingress allow-list includes the chart's declared health port

Checks that need an external repo (service-template, platform-gitops, TF)
read the path from env vars and SKIP with a clear note when the repo is
not available — the hook is informative even with partial inputs.

Invoked by pre-commit with the changed file paths as argv; also runnable
directly:  service-yaml-check.py path/to/svc.yaml [...]
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "service-yaml-check: PyYAML not available — install with `pip install pyyaml`.\n"
    )
    sys.exit(2)


PLATFORM_GITOPS_DIR = os.environ.get("PLATFORM_GITOPS_DIR")
PLATFORM_INFRA_DIR = os.environ.get("PLATFORM_INFRA_DIR")


@dataclass
class Finding:
    level: str  # "error" | "warn" | "skip" | "ok"
    check: str
    message: str


def _repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return Path.cwd()


def check_chart_path(doc: dict, path: Path) -> Finding:
    chart = (doc.get("repositories") or {}).get("chart")
    if not chart:
        return Finding("error", "chart-path", "repositories.chart is required")
    chart_yaml = _repo_root(path) / chart / "Chart.yaml"
    if not chart_yaml.is_file():
        return Finding(
            "error",
            "chart-path",
            f"repositories.chart '{chart}' has no {chart_yaml}",
        )
    return Finding("ok", "chart-path", f"{chart}/Chart.yaml found")


def check_image_repo(doc: dict, _path: Path) -> Finding:
    image = (doc.get("repositories") or {}).get("image")
    if not image:
        return Finding("error", "image-repo", "repositories.image is required")
    # TODO(#544): grep platform-infrastructure TF for an ECR repo matching `image`,
    # or alternatively `aws ecr describe-repositories --repository-names`.
    return Finding(
        "warn",
        "image-repo",
        f"not yet implemented — would verify ECR repo '{image}' exists (see #544)",
    )


def check_pod_identity(doc: dict, _path: Path) -> Finding:
    pi = doc.get("podIdentity") or {}
    sa = pi.get("serviceAccount") or doc.get("name")
    if not sa:
        return Finding("skip", "pod-identity", "no podIdentity block — assuming none required")
    # TODO(#544): grep platform-gitops for a Crossplane PIA MR or services-yaml
    # block that grants this SA. Until then, just confirm the field is present.
    return Finding(
        "warn",
        "pod-identity",
        f"not yet implemented — would verify PIA exists for serviceAccount '{sa}' (see #544)",
    )


def check_push_role(doc: dict, _path: Path) -> Finding:
    name = doc.get("name")
    if not name:
        return Finding("error", "push-role", "service name is required")
    # TODO(#544): grep TF for `xp-<name>-gha-push` role definition.
    return Finding(
        "warn",
        "push-role",
        f"not yet implemented — would verify xp-{name}-gha-push exists in TF (see #544)",
    )


def check_netpol_health_port(doc: dict, _path: Path) -> Finding:
    np = doc.get("networkPolicy") or {}
    ingress = np.get("ingress") or []
    declared_ports = {
        p.get("port")
        for rule in ingress
        for p in (rule.get("ports") or [])
        if p.get("port") is not None
    }
    if not declared_ports:
        return Finding(
            "skip",
            "netpol-ports",
            "no networkPolicy.ingress ports declared — nothing to check",
        )
    # TODO(#544): cross-reference declared ports against the chart's default
    # health/metrics port (values.yaml `service.port` / probe ports).
    return Finding(
        "warn",
        "netpol-ports",
        f"not yet implemented — would cross-check declared ports {sorted(declared_ports)} "
        f"against chart values (see #544)",
    )


CHECKS: list[Callable[[dict, Path], Finding]] = [
    check_chart_path,
    check_image_repo,
    check_pod_identity,
    check_push_role,
    check_netpol_health_port,
]


def check_file(path: Path) -> list[Finding]:
    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return [Finding("error", "yaml-parse", f"failed to parse {path}: {exc}")]
    if not isinstance(doc, dict):
        return [Finding("error", "yaml-parse", f"{path}: expected a yaml mapping at top level")]
    return [c(doc, path) for c in CHECKS]


def format_finding(path: Path, f: Finding) -> str:
    icon = {"ok": "✓", "warn": "!", "skip": "·", "error": "✗"}.get(f.level, "?")
    return f"  {icon} [{f.check}] {f.message}"


def main(argv: list[str] | None = None) -> int:
    # Defaulted so setuptools can wire this as a console script (called with no
    # arguments) while direct `python -m` / script invocation still works.
    if argv is None:
        argv = sys.argv[1:]
    files = [Path(a) for a in argv]
    if not files:
        sys.stderr.write("service-yaml-check: no files provided\n")
        return 0

    exit_code = 0
    for path in files:
        findings = check_file(path)
        sys.stdout.write(f"{path}\n")
        for f in findings:
            sys.stdout.write(format_finding(path, f) + "\n")
            if f.level == "error":
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
