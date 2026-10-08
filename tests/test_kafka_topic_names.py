#!/usr/bin/env python3
"""Regression tests for the kafka-topic-names hook.

Plain files in a temp dir — no git repo, no subprocess — so the suite stays fast
enough to run as a pre-commit hook in this repo itself.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pinpredict_hooks.kafka_legacy_topics import LEGACY_TOPICS  # noqa: E402
from pinpredict_hooks.kafka_topic_names import (  # noqa: E402
    main,
    problems_with,
)


def ok(name: str, wildcard_ok: bool = True) -> bool:
    return problems_with(name, wildcard_ok=wildcard_ok) == []


class GrammarTest(unittest.TestCase):
    def test_the_design_docs_own_examples_conform(self) -> None:
        for name in (
            "pinpredict.oms.leans.state.v1",
            "pinpredict.nadex.md.book.state.v1",
            "pinpredict.dis.raw.pinnacle.v1",
            "pinpredict.trades.closing-line.snapshot.v1",
            "pinpredict.mag.markets.v1",  # kind elided
            "pinpredict.trades.events.v1",  # subject elided
            "pinpredict.kalshi.queue-position.events.v1",
            "pinpredict.rfq.fills.events.v2",
        ):
            self.assertTrue(ok(name), name)

    def test_dkex_is_a_venue_domain(self) -> None:
        for name in (
            "pinpredict.dkex.oe.commands.v1",
            "pinpredict.dkex.oe.events.v1",
            "pinpredict.dkex.dropcopy.events.v1",
        ):
            self.assertTrue(ok(name), name)

    def test_the_shapes_that_kept_arriving_after_the_convention_fail(self) -> None:
        # Not legacy-listed variants of the real drift, so the grammar decides.
        for name in (
            "pp-rfq-fills-v2",  # flat pp- prefix
            "oms.exposure.v2",  # no pinpredict prefix, 3 segments
            "rfq-fills",  # flat, unversioned
        ):
            self.assertFalse(ok(name), name)

    def test_underscore_is_rejected_and_says_why(self) -> None:
        problems = problems_with("pinpredict.oms.order_intents.v1", wildcard_ok=False)
        self.assertTrue(any("`_`" in p for p in problems), problems)

    def test_each_rule(self) -> None:
        cases = {
            "pinpredict.oms.leans.state": "version",
            "pinpredict.oms.leans.state.1": "version",
            "pinpredict.oms.Leans.state.v1": "lowercase",
            "pinpredict.trader-tools.settings.commands.v1": "domain",  # a service name
            "pinpredict.oms.v1": "segment",  # too short
            "pinpredict.oms.a.b.c.state.v1": "segment",  # too long
            "pinpredict.oms.a.b.c.v1": "kind",  # 3 subjects, no kind
            "pinpredict.oms.state.leans.v1": "kind word",  # rule 7
            "acme.oms.leans.state.v1": "pinpredict",
        }
        for name, expect in cases.items():
            problems = problems_with(name, wildcard_ok=False)
            self.assertTrue(problems, name)
            self.assertTrue(any(expect in p for p in problems), (name, problems))

    def test_infra_internal_names(self) -> None:
        self.assertTrue(ok("__connect-offsets"))
        self.assertTrue(ok("__mm2-trades-status"))
        self.assertFalse(ok("__Connect_offsets"))

    def test_prefix_grants(self) -> None:
        self.assertTrue(ok("pinpredict.mag.*"))
        self.assertTrue(ok("pinpredict.dis.raw.*"))
        self.assertFalse(ok("pinpredict.*"))  # no domain
        self.assertFalse(ok("pinpredict.mag*"))  # not a dotted prefix
        self.assertFalse(ok("pp-*"))
        self.assertFalse(ok("pinpredict.mag.*", wildcard_ok=False))  # provisioning

    def test_legacy_names_pass_and_the_list_carries_no_conforming_name(self) -> None:
        for name in LEGACY_TOPICS:
            self.assertTrue(ok(name), name)
        # A conforming name in the allowlist is dead weight: it would keep
        # passing if the grammar check broke, so it proves nothing.
        conforming = sorted(n for n in LEGACY_TOPICS if problems_with_unlisted(n) == [])
        self.assertEqual(conforming, [])


def problems_with_unlisted(name: str) -> list[str]:
    """Grammar verdict for `name` as if it were not grandfathered."""
    import pinpredict_hooks.kafka_topic_names as mod

    original = mod.LEGACY_TOPICS
    mod.LEGACY_TOPICS = frozenset()
    try:
        return mod.problems_with(name, wildcard_ok=True)
    finally:
        mod.LEGACY_TOPICS = original


SPEC = """\
name: rfq-pricer
podIdentity:
  permissions:
    msk:
      readTopics:
        - {read}
      writeTopics:
        - {write}
      groups:
        - rfq_pricer_GROUP
provisionTopics:
  - name: {provision}
    partitions: 3
"""


class SpecFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / ".platform" / "services"
        self.dir.mkdir(parents=True)

    def spec(self, **names: str) -> str:
        fields = {
            "read": "pinpredict.mag.*",
            "write": "pinpredict.rfq.fills.events.v1",
            "provision": "pinpredict.rfq.fills.events.v1",
        }
        fields.update(names)
        path = self.dir / "rfq-pricer.yaml"
        path.write_text(SPEC.format(**fields), encoding="utf-8")
        return str(path)

    def test_conforming_spec_passes_and_groups_are_not_topics(self) -> None:
        # `rfq_pricer_GROUP` would fail the grammar; it must not be checked.
        self.assertEqual(main([self.spec()]), 0)

    def test_new_flat_topic_in_provision_fails(self) -> None:
        self.assertEqual(main([self.spec(provision="pp-rfq-quotes")]), 1)

    def test_new_flat_topic_in_a_grant_fails(self) -> None:
        self.assertEqual(main([self.spec(write="rfq.quotes.v1")]), 1)

    def test_legacy_topic_in_a_grant_passes(self) -> None:
        legacy = sorted(n for n in LEGACY_TOPICS if "*" not in n)[0]
        self.assertEqual(main([self.spec(read=legacy)]), 0)

    def test_wildcard_cannot_be_provisioned(self) -> None:
        self.assertEqual(main([self.spec(provision="pinpredict.rfq.*")]), 1)

    def test_names_are_found_wherever_the_field_sits(self) -> None:
        path = self.dir / "odd.yaml"
        path.write_text("a:\n  b:\n    - topics:\n        - pp-new-thing\n", encoding="utf-8")
        self.assertEqual(main([str(path)]), 1)

    def test_missing_file_is_a_no_op(self) -> None:
        self.assertEqual(main([str(self.dir / "gone.yaml")]), 0)

    def test_malformed_yaml_is_fatal(self) -> None:
        path = self.dir / "bad.yaml"
        path.write_text("readTopics: [unclosed\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            main([str(path)])


if __name__ == "__main__":
    unittest.main()
