#!/usr/bin/env python3
"""Regression tests for the k5s-stack-namespaces hook.

Plain files in a temp dir — no git repo, no subprocess — so the suite stays fast
enough to run as a pre-commit hook in this repo itself.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pinpredict_hooks.k5s_stack_namespaces import main  # noqa: E402


def lane(ns: str | None, extends: str | None = None) -> str:
    body = "services:\n  oms:\n    image: img\n"
    if ns is not None:
        body = f"namespace: {ns}\n" + body
    if extends is not None:
        body = f"extends:\n  - {extends}\n" + body
    return body


class K5sStackNamespacesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "overlays"
        self.dir.mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name: str, body: str) -> Path:
        path = self.dir / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_unique_namespaces_pass(self) -> None:
        a = self.write("perf-5x.yaml", lane("perf-rig-5x"))
        self.write("perf-10x.yaml", lane("perf-rig-10x"))
        self.assertEqual(main([str(a)]), 0)

    def test_duplicate_namespace_fails_and_names_both_files(self) -> None:
        # The realistic mistake: perf-20x started as a copy of perf-10x.
        a = self.write("perf-10x.yaml", lane("perf-rig-10x"))
        self.write("perf-20x.yaml", lane("perf-rig-10x"))
        self.assertEqual(main([str(a)]), 1)

    def test_collision_is_caught_when_only_the_new_file_is_staged(self) -> None:
        """A collision is a property of the whole SET, not the changed files.

        pre-commit passes only what this commit touched, so the lane that already
        owned the namespace is usually absent from argv. Comparing just the staged
        set would pass every time the older file is untouched — i.e. always.
        """
        self.write("perf-10x.yaml", lane("perf-rig-10x"))
        new = self.write("perf-20x.yaml", lane("perf-rig-10x"))
        self.assertEqual(main([str(new)]), 1)

    def test_overlay_without_a_namespace_is_skipped(self) -> None:
        """Inheriting the base stack's namespace is the normal lane shape."""
        a = self.write("perf-5x.yaml", lane(None))
        self.write("perf-10x.yaml", lane(None))
        self.assertEqual(main([str(a)]), 0)

    def test_shared_namespace_via_extends_is_still_caught(self) -> None:
        """Files are read AS WRITTEN, not through k5s's extends resolution.

        Two lanes that end up in one namespace because they both inherit it from a
        shared fragment is the same collision; resolving first would hide it. Here
        the fragment declares the namespace and neither lane overrides it, so
        neither lane declares one — nothing to compare, and the hook stays quiet.
        Restating it in both lanes is what it catches.
        """
        self.write("_shared.yaml", "namespace: perf-rig\n")
        a = self.write("perf-5x.yaml", lane("perf-rig", extends="_shared.yaml"))
        self.write("perf-10x.yaml", lane("perf-rig", extends="_shared.yaml"))
        self.assertEqual(main([str(a)]), 1)

    def test_no_files_is_a_clean_noop(self) -> None:
        self.assertEqual(main([]), 0)

    def test_malformed_yaml_is_fatal_not_skipped(self) -> None:
        """Silently passing on unparseable YAML is how a guard stops guarding."""
        bad = self.write("perf-5x.yaml", "namespace: [unclosed\n")
        with self.assertRaises(SystemExit):
            main([str(bad)])


if __name__ == "__main__":
    unittest.main()
