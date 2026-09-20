"""Tests for hooks/check-go-version-sync.sh.

The shell hooks had no tests at all, which is the failure this repo's own
.pre-commit-config.yaml warns about ("a hook whose tests only run in CI is
exactly how service-yaml-check stayed broken"). Each case below is a layout
that reached a real repo: the nested pin is trader-tools', the missing root pin
is keyhole/ppiam/trading-reports, and the sibling-module case is what the old
nearest-ancestor resolution skipped while reporting success.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "check-go-version-sync.sh"


class CheckGoVersionSync(unittest.TestCase):
    def run_hook(self, files):
        """Materialize {relpath: content} in a temp repo and run the hook in it."""
        with tempfile.TemporaryDirectory() as d:
            for rel, content in files.items():
                p = Path(d) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            proc = subprocess.run(
                ["bash", str(HOOK)], cwd=d, capture_output=True, text=True
            )
            return proc.returncode, proc.stdout + proc.stderr

    # ── the happy path ────────────────────────────────────────────────────
    def test_root_pin_and_matching_modules_pass(self):
        rc, out = self.run_hook({
            ".tool-versions": "golang 1.26.6\n",
            "apps/a/go.mod": "module a\n\ngo 1.26.6\n",
            "apps/b/go.mod": "module b\n\ngo 1.26.6\n",
            "chaos/go.mod": "module c\n\ngo 1.26.6\n",
        })
        self.assertEqual(rc, 0, out)

    def test_repo_with_no_go_mod_is_ignored(self):
        rc, out = self.run_hook({".tool-versions": "nodejs 24.15.0\n"})
        self.assertEqual(rc, 0, out)

    def test_nested_tool_versions_without_golang_is_allowed(self):
        # apps/x pins golangci-lint / nodejs but not golang — legal.
        rc, out = self.run_hook({
            ".tool-versions": "golang 1.26.6\n",
            "apps/x/.tool-versions": "golangci-lint 2.12.2\n",
            "apps/x/go.mod": "module x\n\ngo 1.26.6\n",
        })
        self.assertEqual(rc, 0, out)

    # ── 1. root-only ──────────────────────────────────────────────────────
    def test_nested_golang_pin_is_rejected(self):
        rc, out = self.run_hook({
            ".tool-versions": "golang 1.26.6\n",
            "apps/a/.tool-versions": "golang 1.26.6\n",
            "apps/a/go.mod": "module a\n\ngo 1.26.6\n",
        })
        self.assertEqual(rc, 1, out)
        self.assertIn("apps/a/.tool-versions", out)
        self.assertIn("outside the repo root", out)

    def test_nested_pin_rejected_even_when_it_agrees_with_root(self):
        # The values agreeing today is exactly what makes this quiet: the two
        # files still drift independently tomorrow.
        rc, out = self.run_hook({
            ".tool-versions": "golang 1.26.6\n",
            "sub/.tool-versions": "golang 1.26.6\n",
            "sub/go.mod": "module s\n\ngo 1.26.6\n",
        })
        self.assertEqual(rc, 1, out)

    def test_vendor_and_node_modules_pins_are_ignored(self):
        rc, out = self.run_hook({
            ".tool-versions": "golang 1.26.6\n",
            "go.mod": "module r\n\ngo 1.26.6\n",
            "vendor/dep/.tool-versions": "golang 1.20.0\n",
            "node_modules/pkg/.tool-versions": "golang 1.19.0\n",
        })
        self.assertEqual(rc, 0, out)

    # ── 2. a root pin is required once any module exists ──────────────────
    def test_go_mod_without_root_pin_is_rejected(self):
        rc, out = self.run_hook({"go.mod": "module r\n\ngo 1.26.4\n"})
        self.assertEqual(rc, 1, out)
        self.assertIn("no 'golang' pin", out)

    def test_missing_root_pin_lists_every_module(self):
        rc, out = self.run_hook({
            "apps/a/go.mod": "module a\n\ngo 1.26.6\n",
            "apps/b/go.mod": "module b\n\ngo 1.26.6\n",
        })
        self.assertEqual(rc, 1, out)
        self.assertIn("apps/a/go.mod", out)
        self.assertIn("apps/b/go.mod", out)

    # ── 3. every module matches the root pin ──────────────────────────────
    def test_module_mismatch_is_rejected(self):
        rc, out = self.run_hook({
            ".tool-versions": "golang 1.26.6\n",
            "go.mod": "module r\n\ngo 1.26.4\n",
        })
        self.assertEqual(rc, 1, out)
        self.assertIn("'go 1.26.4'", out)
        self.assertIn("'golang 1.26.6'", out)

    def test_every_module_is_checked_not_just_the_first(self):
        # The regression the old nearest-ancestor walk allowed: a sibling module
        # with no governing pin was skipped while the hook exited 0.
        rc, out = self.run_hook({
            ".tool-versions": "golang 1.26.6\n",
            "apps/backend-go/go.mod": "module a\n\ngo 1.26.6\n",
            "apps/scribe/go.mod": "module b\n\ngo 1.26.5\n",
            "chaos/go.mod": "module c\n\ngo 1.26.4\n",
        })
        self.assertEqual(rc, 1, out)
        self.assertIn("apps/scribe/go.mod", out)
        self.assertIn("chaos/go.mod", out)

    def test_module_with_no_go_directive_is_skipped(self):
        rc, out = self.run_hook({
            ".tool-versions": "golang 1.26.6\n",
            "go.mod": "module r\n",
        })
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
