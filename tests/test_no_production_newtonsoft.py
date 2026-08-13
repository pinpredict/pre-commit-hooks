#!/usr/bin/env python3
"""Regression tests for the no-production-newtonsoft hook.

The static-scan cases here were ported from trading's
`scripts/ci/test_check_no_production_newtonsoft.py` when the scan moved into
this repo. Trading kept the package-graph tests, which cover the `dotnet`-
dependent half that stays in its CI.

These need a real git repo because the hook enumerates files with
`git ls-files` — an intentional part of its contract (whole-tree scanning, so a
violation in an untouched file still fails). `git init` on a temp dir is a few
milliseconds, so the suite still runs as a hook in this repo.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pinpredict_hooks.no_production_newtonsoft import (  # noqa: E402
    central_version_pattern,
    find_static_violations,
    main,
)

ALLOWED = ("Acme.Tests/", "Acme.Benchmarks/")
CENTRAL = "Directory.Packages.props"
PATTERN = central_version_pattern("Newtonsoft.Json")


class Repo:
    """A temp git repo holding the tracked files the hook scans."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, relative: str, content: str) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def track(self) -> None:
        subprocess.run(
            ["git", "-c", "init.defaultBranch=main", "init", "-q", "--template=", "."],
            cwd=self.root,
            check=True,
        )
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)

    def run(self, *args: str) -> int:
        return main(
            [
                f"--root={self.root}",
                *(f"--allow-prefix={prefix}" for prefix in ALLOWED),
                f"--central-version-file={CENTRAL}",
                *args,
            ]
        )


class StaticScanTests(unittest.TestCase):
    def make_repo(self) -> Repo:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Repo(Path(directory.name))

    def scan(self, repo: Repo, paths: list[str]) -> list[tuple[Path, int]]:
        return find_static_violations(
            repo.root, [Path(p) for p in paths], "newtonsoft", ALLOWED, CENTRAL, PATTERN
        )

    def test_scan_is_case_insensitive_and_includes_build_files(self) -> None:
        repo = self.make_repo()
        repo.write("Acme.Api/Program.cs", "using NEWTONSOFT.Json;\n")
        repo.write(
            "Acme.Api/Acme.Api.csproj",
            '<Project><ItemGroup><PackageReference Include="newtonsoft.json" />'
            "</ItemGroup></Project>\n",
        )
        repo.write("Directory.Build.props", '<Project><Import Project="Newtonsoft" />\n</Project>')
        self.assertEqual(
            [
                (Path("Acme.Api/Program.cs"), 1),
                (Path("Acme.Api/Acme.Api.csproj"), 1),
                (Path("Directory.Build.props"), 1),
            ],
            self.scan(
                repo,
                [
                    "Acme.Api/Program.cs",
                    "Acme.Api/Acme.Api.csproj",
                    "Directory.Build.props",
                ],
            ),
        )

    def test_scan_keeps_only_explicit_compatibility_exceptions(self) -> None:
        repo = self.make_repo()
        repo.write("Acme.Tests/JsonTests.cs", "using Newtonsoft.Json;\n")
        repo.write("Acme.Benchmarks/Bench.cs", "using Newtonsoft.Json;\n")
        repo.write(
            CENTRAL,
            '<Project><ItemGroup>\n<PackageVersion Include="Newtonsoft.Json" '
            'Version="13.0.3" />\n</ItemGroup></Project>\n',
        )
        self.assertEqual(
            [],
            self.scan(
                repo,
                ["Acme.Tests/JsonTests.cs", "Acme.Benchmarks/Bench.cs", CENTRAL],
            ),
        )

    def test_a_lookalike_prefix_is_not_exempt(self) -> None:
        """`Acme.TestsSupport/` must not inherit `Acme.Tests/`'s exemption."""
        repo = self.make_repo()
        repo.write("Acme.TestSupport/Helper.cs", "using Newtonsoft.Json;\n")
        self.assertEqual(
            [(Path("Acme.TestSupport/Helper.cs"), 1)],
            self.scan(repo, ["Acme.TestSupport/Helper.cs"]),
        )

    def test_central_version_exemption_is_scoped_to_the_named_file(self) -> None:
        repo = self.make_repo()
        line = '<PackageVersion Include="Newtonsoft.Json" Version="13.0.3" />\n'
        repo.write("Acme.Api/Acme.Api.csproj", line)
        self.assertEqual(
            [(Path("Acme.Api/Acme.Api.csproj"), 1)],
            self.scan(repo, ["Acme.Api/Acme.Api.csproj"]),
        )

    def test_central_file_still_fails_on_a_non_packageversion_reference(self) -> None:
        repo = self.make_repo()
        repo.write(CENTRAL, '<PackageReference Include="Newtonsoft.Json" />\n')
        self.assertEqual([(Path(CENTRAL), 1)], self.scan(repo, [CENTRAL]))

    def test_end_to_end_clean_tree_passes(self) -> None:
        repo = self.make_repo()
        repo.write("Acme.Api/Program.cs", "using System.Text.Json;\n")
        repo.write("Acme.Tests/JsonTests.cs", "using Newtonsoft.Json;\n")
        repo.track()
        self.assertEqual(0, repo.run())

    def test_end_to_end_violation_fails(self) -> None:
        repo = self.make_repo()
        repo.write("Acme.Api/Program.cs", "using Newtonsoft.Json;\n")
        repo.track()
        self.assertEqual(1, repo.run())

    def test_an_untouched_file_still_fails_the_whole_tree_scan(self) -> None:
        """The policy is a tree property — staged-file scoping would hide this."""
        repo = self.make_repo()
        repo.write("Acme.Api/Legacy.cs", "using Newtonsoft.Json;\n")
        repo.write("Acme.Api/Program.cs", "using System.Text.Json;\n")
        repo.track()
        self.assertEqual(1, repo.run("Acme.Api/Program.cs"))

    def test_a_repo_with_no_matching_sources_is_a_clean_no_op(self) -> None:
        repo = self.make_repo()
        repo.write("README.md", "# nothing to scan\n")
        repo.track()
        self.assertEqual(0, repo.run())

    def test_no_allow_prefix_permits_nothing(self) -> None:
        repo = self.make_repo()
        repo.write("Acme.Tests/JsonTests.cs", "using Newtonsoft.Json;\n")
        repo.track()
        self.assertEqual(1, main([f"--root={repo.root}"]))

    def test_token_is_configurable(self) -> None:
        repo = self.make_repo()
        repo.write("Acme.Api/Program.cs", "using ServiceStack.Text;\n")
        repo.track()
        self.assertEqual(1, main([f"--root={repo.root}", "--token=servicestack"]))
        self.assertEqual(0, main([f"--root={repo.root}"]))


if __name__ == "__main__":
    unittest.main()
