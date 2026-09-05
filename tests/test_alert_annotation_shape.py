#!/usr/bin/env python3
"""Regression tests for the alert-annotation-shape hook.

Plain files in a temp dir — no git repo, no subprocess — so the suite stays fast
enough to run as a pre-commit hook in this repo itself.

Each case is one of the Slack failures the hook exists to prevent, written the
way it actually appeared in a chart rather than reduced to a minimal trigger.
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pinpredict_hooks.alert_annotation_shape import main  # noqa: E402

GOOD = """\
groups:
  - name: kalshi
    rules:
      - alert: KalshiOrderGroupBindingsAbsent
        expr: up == 0
        annotations:
          title: Kalshi order-group bindings are missing
          description: >-
            The order-group update stream is the only way a trip becomes
            knowable, and it has produced no frame for 15 minutes.
"""


class AlertAnnotationShapeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "charts" / "svc" / "templates"
        self.root.mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)

    def run_hook(self, body: str, *args: str) -> tuple[int, str]:
        (self.root / "alerts.yaml").write_text(body, encoding="utf-8")
        root = str(Path(self._tmp.name) / "charts")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["--root", root, *args])
        return code, buf.getvalue()

    # --- the clean case, and the shapes that must NOT be flagged -------------

    def test_well_formed_rule_passes(self) -> None:
        code, out = self.run_hook(GOOD)
        self.assertEqual(code, 0, out)

    def test_file_without_alerts_is_ignored(self) -> None:
        code, out = self.run_hook("replicaCount: 2\nimage:\n  tag: v1\n")
        self.assertEqual(code, 0, out)

    def test_plural_s_after_braces_is_not_a_duration(self) -> None:
        """`}}s` is only a unit when a duration precedes it — else it is a plural."""
        code, out = self.run_hook(
            GOOD.replace(
                "knowable, and it has produced no frame for 15 minutes.",
                "knowable. {{ $labels.venue }}s bindings are all absent.",
            )
        )
        self.assertEqual(code, 0, out)

    def test_helm_control_lines_are_not_prose(self) -> None:
        body = GOOD.replace(
            "          description: >-\n",
            "          description: >-\n            {{- if .Values.verbose }}\n",
        )
        code, out = self.run_hook(body)
        self.assertEqual(code, 0, out)

    # --- one test per check -------------------------------------------------

    def test_missing_title_is_flagged(self) -> None:
        code, out = self.run_hook(GOOD.replace("          title: Kalshi order-group bindings are missing\n", ""))
        self.assertEqual(code, 1)
        self.assertIn("no `title` annotation", out)

    def test_interpolated_title_is_flagged(self) -> None:
        code, out = self.run_hook(
            GOOD.replace("title: Kalshi order-group bindings are missing", "title: {{ $labels.venue }} bindings missing")
        )
        self.assertEqual(code, 1)
        self.assertIn("`title` interpolates", out)

    def test_overlong_title_is_flagged(self) -> None:
        code, out = self.run_hook(GOOD.replace("Kalshi order-group bindings are missing", "K" * 61))
        self.assertEqual(code, 1)
        self.assertIn("max 60", out)

    def test_max_title_is_configurable(self) -> None:
        long_title = "K" * 61
        code, _ = self.run_hook(GOOD.replace("Kalshi order-group bindings are missing", long_title), "--max-title", "80")
        self.assertEqual(code, 0)

    def test_literal_description_is_flagged(self) -> None:
        code, out = self.run_hook(GOOD.replace("description: >-", "description: |"))
        self.assertEqual(code, 1)
        self.assertIn("literal block", out)

    def test_literal_description_is_reported_once(self) -> None:
        """The style is a property of the block; N lines must not mean N reports."""
        code, out = self.run_hook(GOOD.replace("description: >-", "description: |"))
        self.assertEqual(code, 1)
        self.assertEqual(out.count("literal block"), 1)

    def test_blockquote_paragraph_is_flagged(self) -> None:
        body = GOOD.replace(
            "            The order-group update stream is the only way a trip becomes\n",
            "            >1000ms is the threshold and the venue is past it.\n",
        )
        code, out = self.run_hook(body)
        self.assertEqual(code, 1)
        self.assertIn("blockquote", out)

    def test_raw_seconds_from_value_is_flagged(self) -> None:
        body = GOOD.replace(
            "for 15 minutes.",
            'for {{ $value | printf "%.0f" }}s.',
        )
        code, out = self.run_hook(body)
        self.assertEqual(code, 1)
        self.assertIn("raw seconds", out)

    def test_raw_seconds_from_helm_value_is_flagged(self) -> None:
        body = GOOD.replace(
            "for 15 minutes.",
            "for {{ .Values.staleAfterSeconds }}s.",
        )
        code, out = self.run_hook(body)
        self.assertEqual(code, 1)
        self.assertIn("raw seconds", out)

    # --- adoption controls --------------------------------------------------

    def test_skip_disables_one_check_only(self) -> None:
        """A repo with a literal-block backlog still gets the other five."""
        body = GOOD.replace("description: >-", "description: |").replace(
            "          title: Kalshi order-group bindings are missing\n", ""
        )
        code, out = self.run_hook(body, "--skip", "literal-description")
        self.assertEqual(code, 1)
        self.assertNotIn("literal block", out)
        self.assertIn("no `title` annotation", out)

    def test_missing_root_is_a_clean_no_op(self) -> None:
        code = main(["--root", str(Path(self._tmp.name) / "nope")])
        self.assertEqual(code, 0)

    def test_every_alert_in_a_file_is_checked(self) -> None:
        """The blocks are split on `- alert:`; the second one must not be lost."""
        second = GOOD.split("      - alert:")[1]
        body = GOOD + "      - alert:" + second.replace(
            "KalshiOrderGroupBindingsAbsent", "KalshiSecondRule"
        ).replace("          title: Kalshi order-group bindings are missing\n", "")
        code, out = self.run_hook(body)
        self.assertEqual(code, 1)
        self.assertIn("KalshiSecondRule", out)


if __name__ == "__main__":
    unittest.main()
