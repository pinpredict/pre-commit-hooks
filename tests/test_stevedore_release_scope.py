#!/usr/bin/env python3
"""Regression tests for the stevedore-release-scope hook.

These write plain files into a temp dir — no git repo, no subprocess — so the
whole suite stays fast enough to run as a pre-commit hook in this repo itself.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pinpredict_hooks.stevedore_release_scope import main  # noqa: E402

TRADING_SELECTOR = "${{ github.event_name == 'workflow_dispatch' && inputs.services || '' }}"


def catalog(images: list[tuple[str, str | None]], shared: list[str] | None) -> str:
    lines = ["images:"]
    for image_id, project in images:
        lines.append(f"  - id: {image_id}")
        if project:
            lines.append(f"    project: {project}")
    if shared is not None:
        lines.append("change_detection:")
        lines.append("  shared_paths:")
        for path in shared:
            lines.append(f'    - "{path}"')
    return "\n".join(lines) + "\n"


def workflow(docker_only: str | None, chart_only: str | None) -> str:
    lines = ["name: CI", "on:", "  push:", "    branches: [main]", "jobs:"]
    for job, selector in (("docker-release", docker_only), ("chart-release", chart_only)):
        if selector is None:
            continue
        lines.append(f"  {job}:")
        lines.append("    uses: pinpredict/.github/.github/workflows/x.yml@main")
        lines.append("    with:")
        lines.append(f'      only: "{selector}"')
    return "\n".join(lines) + "\n"


class Repo:
    """A temp directory shaped like the files the hook reads."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, relative: str, content: str) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def seed(self) -> None:
        self.write(
            ".stevedore.yaml",
            catalog([("oms", "PinPredict/PinPredict.csproj")], ["Directory.Build.props"]),
        )
        self.write("charts/oms/Chart.yaml", "name: oms\nversion: 0.1.0\n")
        self.write(
            ".github/workflows/ci.yml", workflow(TRADING_SELECTOR, TRADING_SELECTOR)
        )

    def run(self, *args: str) -> int:
        return main(
            [
                f"--catalog={self.root / '.stevedore.yaml'}",
                f"--workflow={self.root / '.github/workflows/ci.yml'}",
                f"--charts-dir={self.root / 'charts'}",
                *args,
            ]
        )


class StevedoreReleaseScopeTests(unittest.TestCase):
    def make_repo(self) -> Repo:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        repo = Repo(Path(directory.name))
        repo.seed()
        return repo

    def test_a_well_formed_repo_passes(self) -> None:
        repo = self.make_repo()
        self.assertEqual(
            0,
            repo.run(
                "--service=oms",
                "--require-shared-path=Directory.Build.props",
                "--forbid-shared-path=Dockerfile",
            ),
        )

    def test_missing_catalog_is_a_no_op(self) -> None:
        repo = self.make_repo()
        (repo.root / ".stevedore.yaml").unlink()
        self.assertEqual(0, repo.run("--service=oms"))

    def test_unknown_service_fails(self) -> None:
        repo = self.make_repo()
        self.assertEqual(1, repo.run("--service=nadex-rfqgw"))

    def test_service_without_a_sibling_chart_fails(self) -> None:
        repo = self.make_repo()
        repo.write(".stevedore.yaml", catalog([("oms", None), ("rfqgw", None)], None))
        self.assertEqual(1, repo.run("--service=rfqgw"))

    def test_chart_name_must_match_the_image_id(self) -> None:
        repo = self.make_repo()
        repo.write("charts/oms/Chart.yaml", "name: order-management\nversion: 0.1.0\n")
        self.assertEqual(1, repo.run("--service=oms"))

    def test_forbidden_shared_path_fails(self) -> None:
        repo = self.make_repo()
        repo.write(
            ".stevedore.yaml",
            catalog([("oms", None)], ["Directory.Build.props", "Dockerfile"]),
        )
        self.assertEqual(1, repo.run("--forbid-shared-path=Dockerfile"))

    def test_required_shared_path_missing_fails(self) -> None:
        repo = self.make_repo()
        repo.write(".stevedore.yaml", catalog([("oms", None)], ["Directory.Packages.props"]))
        self.assertEqual(1, repo.run("--require-shared-path=Directory.Build.props"))

    def test_absent_shared_paths_key_fails_a_required_path(self) -> None:
        repo = self.make_repo()
        repo.write(".stevedore.yaml", catalog([("oms", None)], None))
        self.assertEqual(1, repo.run("--require-shared-path=Directory.Build.props"))

    def test_absent_shared_paths_key_satisfies_forbidden_paths(self) -> None:
        repo = self.make_repo()
        repo.write(".stevedore.yaml", catalog([("oms", None)], None))
        self.assertEqual(0, repo.run("--forbid-shared-path=Dockerfile"))

    def test_divergent_release_selectors_fail(self) -> None:
        repo = self.make_repo()
        repo.write(".github/workflows/ci.yml", workflow(TRADING_SELECTOR, "''"))
        self.assertEqual(1, repo.run("--service=oms"))

    def test_a_repo_without_a_chart_release_job_skips_the_pairing_check(self) -> None:
        repo = self.make_repo()
        repo.write(".github/workflows/ci.yml", workflow(TRADING_SELECTOR, None))
        self.assertEqual(0, repo.run("--service=oms"))

    def test_expected_selector_mismatch_fails(self) -> None:
        repo = self.make_repo()
        other = "${{ (github.event_name == 'workflow_dispatch' && inputs.services != 'all') && inputs.services || '' }}"  # noqa: E501
        repo.write(".github/workflows/ci.yml", workflow(other, other))
        self.assertEqual(1, repo.run(f"--expect-selector={TRADING_SELECTOR}"))

    def test_expected_selector_match_passes(self) -> None:
        repo = self.make_repo()
        self.assertEqual(0, repo.run(f"--expect-selector={TRADING_SELECTOR}"))

    def test_missing_workflow_skips_selector_checks(self) -> None:
        repo = self.make_repo()
        (repo.root / ".github/workflows/ci.yml").unlink()
        self.assertEqual(0, repo.run("--service=oms", f"--expect-selector={TRADING_SELECTOR}"))

    def test_all_violations_are_reported_in_one_run(self) -> None:
        repo = self.make_repo()
        repo.write(".stevedore.yaml", catalog([("oms", None)], ["Dockerfile"]))
        repo.write(".github/workflows/ci.yml", workflow(TRADING_SELECTOR, "''"))
        # Unknown service + missing required path + forbidden path + selector drift.
        self.assertEqual(
            1,
            repo.run(
                "--service=missing",
                "--require-shared-path=Directory.Build.props",
                "--forbid-shared-path=Dockerfile",
            ),
        )


if __name__ == "__main__":
    unittest.main()
