#!/usr/bin/env python3
"""Reject Newtonsoft.Json references in production .NET sources.

Production code should use `System.Text.Json`; a Newtonsoft reference is allowed
only in explicitly approved test and benchmark projects. This hook is the
**static** half of that policy: a case-insensitive scan of every tracked source
and build file, with no `dotnet` involvement, so it runs on every commit in well
under a second.

The **transitive** half — resolving each project's package graph via
`dotnet list package --include-transitive` to catch Newtonsoft arriving through
a dependency — deliberately does *not* live here. It needs `dotnet restore`,
the solution's private package feeds, and credentials, so it belongs in CI
alongside the SDK install. Consumers keep that guard in their own repo; this
hook covers the direct references, which are the ones a commit introduces.

Every repo-specific detail is a flag, so the hook carries no consumer's layout:

  * `--allow-prefix` — path prefixes where a reference is permitted (the test
    and benchmark projects). Nothing is allowed by default.
  * `--central-version-file` — a central package-management file permitted to
    declare the `PackageVersion` for the forbidden package, since pinning a
    version centrally is how the approved test projects consume it at all.
  * `--source-glob` / `--token` — override the file set and the matched token.

Files are enumerated with `git ls-files` rather than from pre-commit's staged
filenames, and the hook runs with `pass_filenames: false`. That is deliberate:
the policy is a property of the whole tree, so a violation sitting in a file
this commit did not touch must still fail. Scanning only changed files would
let a pre-existing reference stay invisible forever.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from pinpredict_hooks._common import emit

PROG = "no-production-newtonsoft"
LABEL = "production newtonsoft"

DEFAULT_TOKEN = "newtonsoft"
DEFAULT_SOURCE_GLOBS = ("*.cs", "*.csproj", "*.props", "*.targets")


def central_version_pattern(package: str) -> re.Pattern[str]:
    """Match a `<PackageVersion Include="<package>" .../>` declaration."""
    return re.compile(
        rf"<\s*PackageVersion\b[^>]*\bInclude\s*=\s*['\"]{re.escape(package)}['\"][^>]*/?\s*>",
        re.IGNORECASE,
    )


def is_allowed_path(path: Path, allowed_prefixes: tuple[str, ...]) -> bool:
    return path.as_posix().startswith(allowed_prefixes)


def is_allowed_central_version(
    path: Path, line: str, central_file: str | None, pattern: re.Pattern[str]
) -> bool:
    """True for the one line that centrally pins the forbidden package's version.

    Scoped to the named file so a `PackageVersion` element copied into an
    ordinary project file is still a violation.
    """
    return (
        central_file is not None
        and path.as_posix() == central_file
        and bool(pattern.search(line))
    )


def tracked_sources(root: Path, globs: tuple[str, ...]) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", *globs],
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line]


def find_static_violations(
    root: Path,
    paths: list[Path],
    token: str,
    allowed_prefixes: tuple[str, ...],
    central_file: str | None,
    pattern: re.Pattern[str],
) -> list[tuple[Path, int]]:
    needle = token.casefold()
    failures: list[tuple[Path, int]] = []
    for path in paths:
        if is_allowed_path(path, allowed_prefixes):
            continue
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (FileNotFoundError, UnicodeDecodeError):
            # A tracked-but-absent path (mid-rebase) or a mislabeled binary is
            # not this hook's failure to report.
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if needle in line.casefold() and not is_allowed_central_version(
                path, line, central_file, pattern
            ):
                failures.append((path, number))
    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description=__doc__ or "", allow_abbrev=False
    )
    parser.add_argument(
        "--root",
        default=".",
        type=Path,
        help="repository root to scan (default: the working directory)",
    )
    parser.add_argument(
        "--token",
        default=DEFAULT_TOKEN,
        help=f"case-insensitive token that marks a violation (default: {DEFAULT_TOKEN})",
    )
    parser.add_argument(
        "--package",
        default=None,
        metavar="ID",
        help="package id for the central-version exemption (default: <token>.Json)",
    )
    parser.add_argument(
        "--allow-prefix",
        action="append",
        default=[],
        metavar="PREFIX",
        help="path prefix where a reference is permitted, e.g. Acme.Tests/ (repeatable)",
    )
    parser.add_argument(
        "--central-version-file",
        default=None,
        metavar="PATH",
        help="file permitted to declare the package's central PackageVersion",
    )
    parser.add_argument(
        "--source-glob",
        action="append",
        default=[],
        metavar="GLOB",
        help=f"git pathspec to scan (repeatable; default: {' '.join(DEFAULT_SOURCE_GLOBS)})",
    )
    # pre-commit may pass matched filenames even with pass_filenames: false;
    # accept and ignore them so the hook stays robust.
    parser.add_argument("filenames", nargs="*", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    globs = tuple(args.source_glob) or DEFAULT_SOURCE_GLOBS
    package = args.package or f"{args.token}.Json"
    pattern = central_version_pattern(package)
    allowed_prefixes = tuple(args.allow_prefix)

    sources = tracked_sources(args.root, globs)
    failures = find_static_violations(
        args.root,
        sources,
        args.token,
        allowed_prefixes,
        args.central_version_file,
        pattern,
    )

    if failures:
        emit(
            [
                f"{path}:{number} references {args.token!r} — production code must use "
                "System.Text.Json; compatibility references are allowed only under "
                f"{', '.join(allowed_prefixes) or 'no approved prefix'}"
                for path, number in failures
            ],
            LABEL,
        )
        print(
            f"\n{len(failures)} production {args.token} reference(s) in "
            f"{len({path for path, _ in failures})} file(s).",
            file=sys.stderr,
        )
        return 1

    print(f"{PROG}: no direct production {args.token} references in {len(sources)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
