#!/usr/bin/env python3
"""Regression tests for the k5s-fragment-parity hook.

Plain files in a temp dir — no git repo, no subprocess — so the suite stays fast
enough to run as a pre-commit hook in this repo itself.

The central case is the real one: magellan published a fragment pinning seven
collector intervals while the repo's own rig had just dropped them, and both
landed green (magellan#651, #652).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pinpredict_hooks.k5s_fragment_parity import main  # noqa: E402


FRAGMENT_HEAD = "apiVersion: k5s.dev/v1beta1\nkind: Fragment\nname: magellan\n"


class K5sFragmentParityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._cwd = os.getcwd()
        os.chdir(self.root)
        (self.root / "k5s").mkdir()
        (self.root / "overlays").mkdir()

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def fragment(self, env: str) -> None:
        (self.root / "k5s" / "fragment.yaml").write_text(
            FRAGMENT_HEAD + f"services:\n  magellan:\n    image: ecr/magellan\n    env:\n{env}",
            encoding="utf-8",
        )

    def overlay(self, env: str, service: str = "magellan") -> None:
        (self.root / "overlays" / "magellan.yaml").write_text(
            f"services:\n  {service}:\n    build:\n      context: .\n    env:\n{env}",
            encoding="utf-8",
        )

    # ── the case this hook exists for ────────────────────────────────────────

    def test_fragment_pinning_what_the_repo_dropped_fails(self) -> None:
        """magellan#652: the fragment kept seven intervals the owner had removed."""
        self.fragment("      MAG_NADEX_INTERVAL: '60'\n      MAG_DB_NAME: pinpredict\n")
        self.overlay("      MAG_DB_NAME: pinpredict\n")
        self.assertEqual(main([]), 1)

    def test_shared_key_disagreeing_fails(self) -> None:
        self.fragment("      MAG_DB_NAME: pinpredict\n")
        self.overlay("      MAG_DB_NAME: something-else\n")
        self.assertEqual(main([]), 1)

    def test_agreeing_passes(self) -> None:
        self.fragment("      MAG_DB_NAME: pinpredict\n")
        self.overlay("      MAG_DB_NAME: pinpredict\n")
        self.assertEqual(main([]), 0)

    # ── what must NOT be flagged ─────────────────────────────────────────────

    def test_parameterized_values_are_not_drift(self) -> None:
        """${input:...} is not a claim about the value, so it cannot disagree."""
        self.fragment("      MAG_DB_HOST: ${input:dbHost}\n")
        self.overlay("      MAG_DB_HOST: postgres.svc\n")
        self.assertEqual(main([]), 0)

    def test_owner_builds_consumer_pulls_is_not_drift(self) -> None:
        """build/image/tag differ by design and are ignored by default."""
        self.fragment("      MAG_DB_NAME: pinpredict\n")
        self.overlay("      MAG_DB_NAME: pinpredict\n")
        self.assertEqual(main([]), 0)  # fragment has image:, overlay has build:

    def test_ignore_silences_a_deliberate_difference(self) -> None:
        self.fragment("      MAG_NADEX_INTERVAL: '60'\n")
        self.overlay("      MAG_DB_NAME: pinpredict\n")
        self.assertEqual(main(["--ignore", "MAG_NADEX_INTERVAL", "--ignore", "MAG_DB_NAME"]), 0)

    def test_no_one_sided_only_checks_disagreements(self) -> None:
        self.fragment("      MAG_NADEX_INTERVAL: '60'\n")
        self.overlay("      MAG_DB_NAME: pinpredict\n")
        self.assertEqual(main(["--no-one-sided"]), 0)

    # ── service naming ───────────────────────────────────────────────────────

    def test_service_name_mapping(self) -> None:
        """magellan's fragment says `magellan`; its own rig says `magellan-api`."""
        self.fragment("      MAG_DB_NAME: pinpredict\n")
        self.overlay("      MAG_DB_NAME: nope\n", service="magellan-api")
        self.assertEqual(main([]), 0, "unmapped name must not match, so nothing to compare")
        self.assertEqual(main(["--service", "magellan=magellan-api"]), 1)

    # ── clean no-ops ─────────────────────────────────────────────────────────

    def test_repo_publishing_no_fragment_is_a_noop(self) -> None:
        self.overlay("      MAG_DB_NAME: pinpredict\n")
        self.assertEqual(main([]), 0)

    def test_fragment_for_a_service_the_repo_does_not_run_is_a_noop(self) -> None:
        self.fragment("      MAG_DB_NAME: pinpredict\n")
        self.overlay("      OTHER: x\n", service="something-else")
        self.assertEqual(main([]), 0)

    def test_list_form_env_is_normalized(self) -> None:
        (self.root / "k5s" / "fragment.yaml").write_text(
            FRAGMENT_HEAD + "services:\n  magellan:\n    env:\n      A: '1'\n", encoding="utf-8"
        )
        (self.root / "overlays" / "magellan.yaml").write_text(
            "services:\n  magellan:\n    env:\n      - A=2\n", encoding="utf-8"
        )
        self.assertEqual(main([]), 1)


if __name__ == "__main__":
    unittest.main()


class AmbiguousTargetTest(K5sFragmentParityTest):
    """A service defined in several lanes must not be silently picked.

    The first run of this hook against magellan compared the fragment to
    `overlays/magellan-go.yaml` — a different lane — because `-go` sorts before
    `.yaml`. A lane's whole job is to override its base, so that comparison
    reports deliberate overrides as drift, against a file nobody meant.
    """

    def test_ambiguous_service_is_an_error_not_a_guess(self) -> None:
        self.fragment("      MAG_DB_NAME: pinpredict\n")
        self.overlay("      MAG_DB_NAME: pinpredict\n")
        (self.root / "overlays" / "magellan-go.yaml").write_text(
            "services:\n  magellan:\n    env:\n      MAG_DB_NAME: magellan\n", encoding="utf-8"
        )
        self.assertEqual(main([]), 1, "two lanes define it — must refuse to choose")

    def test_against_resolves_the_ambiguity(self) -> None:
        self.fragment("      MAG_DB_NAME: pinpredict\n")
        self.overlay("      MAG_DB_NAME: pinpredict\n")
        (self.root / "overlays" / "magellan-go.yaml").write_text(
            "services:\n  magellan:\n    env:\n      MAG_DB_NAME: magellan\n", encoding="utf-8"
        )
        self.assertEqual(main(["--against", "overlays/magellan.yaml"]), 0)


class ScalarRenderingTest(K5sFragmentParityTest):
    """YAML scalars that reach the environment identically are not drift."""

    def test_yaml_bool_equals_quoted_string(self) -> None:
        """trading's fragment says 'false'; its overlay says false. Same setting."""
        self.fragment("      Logging__FileSink__Enabled: 'false'\n")
        self.overlay("      Logging__FileSink__Enabled: false\n")
        self.assertEqual(main([]), 0)

    def test_yaml_bool_true_equals_quoted(self) -> None:
        self.fragment("      Flag: 'true'\n")
        self.overlay("      Flag: true\n")
        self.assertEqual(main([]), 0)

    def test_int_equals_quoted_int(self) -> None:
        self.fragment("      MAG_DB_PORT: '5432'\n")
        self.overlay("      MAG_DB_PORT: 5432\n")
        self.assertEqual(main([]), 0)

    def test_genuinely_different_values_still_fail(self) -> None:
        self.fragment("      Flag: 'true'\n")
        self.overlay("      Flag: false\n")
        self.assertEqual(main([]), 1)
