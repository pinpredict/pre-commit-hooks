"""Kafka topic names that predate the naming convention and are grandfathered.

🚨 This list only ever SHRINKS. A name leaves it when a rename (platform-gitops
`docs/runbooks/rename-a-kafka-topic.md`) has removed the last reference to it.
Never add a name here to get a NEW topic past `kafka-topic-names`; name the
topic to the convention instead. A grandfathered name is not a precedent: the
second block below is what copying one looks like.
"""

from __future__ import annotations

LEGACY_TOPICS = frozenset(
    {
        # The non-conforming rows of platform-gitops
        # `docs/design/kafka-topic-naming-inventory.md` (current-name column),
        # each with a proposed name and a migration tier there.
        "_connect-configs",
        "_connect-offsets",
        "_connect-status",
        "_mm2-configs",
        "_mm2-offsets",
        "_mm2-status",
        "_mm2-trades-configs",
        "_mm2-trades-offsets",
        "_mm2-trades-status",
        "cdna-drop-copy",
        "cdna-trade-capture",
        "oms-intents",
        "oms-seq-log",
        "oms-seq-snapshot",
        "oms-seq-statehash",
        "oms.exposure.v1",
        "oms.leans.v1",
        "oms.order_intents.v1",
        "oms.pullstrategy.state.v1",
        "oms.quote-snapshots.v1",
        "order-events",
        "pinnacle.ingest.fixtures.v1",
        "pinnacle.ingest.gamestate.v1",
        "pinnacle.ingest.heartbeats.v1",
        "pinnacle.ingest.markets.v1",
        "pinnacle.ingest.matrices.v1",
        "pinpredict.dis.raw.opticodds_futures.v1",
        "pinpredict.dis.raw.opticodds_odds.v1",
        "pinpredict.dis.raw.opticodds_props.v1",
        "pinpredict.mag.raw_markets.v1",
        "pp-alerts",
        "pp-closing-line-snapshot",
        "pp-fixture-state",
        "pp-kalshi-md-book",
        "pp-kalshi-md-commands",
        "pp-kalshi-rest-gw-commands",
        "pp-kalshi-rest-gw-signals",
        "pp-nadex-combo-market",
        "pp-nadex-combo-md-commands",
        "pp-nadex-gw-commands",
        "pp-nadex-gw-signals",
        "pp-nadex-md-book",
        "pp-nadex-md-commands",
        "pp-nadex-rfq-commands",
        "pp-nadex-rfq-signals",
        "pp-parlay-evaluation-state",
        "pp-parlay-models",
        "pp-parlay-proposals",
        "pp-parlay-settings",
        "pp-pinnacle-bets",
        "pp-polymarket-md-book",
        "pp-polymarket-md-commands",
        "pp-rfq-info",
        "pp-rfq-trades",
        "pp-rothera-gw-commands",
        "pp-rothera-gw-signals",
        "pp-rothera-md-book",
        "pp-rothera-md-commands",
        "pp-settlements",
        "pp-tob-status",
        "pp-trades",
        "pp-trades-enriched",
        "pp-trades-md-samples",
        "pp-venue-maintenance",
        "pp-venue-registry",
        "pp-venue-status",
        "rothera-drop-copy",
        "settings-commands",
        "trader-tools.presence.v1",
        "trading-commands",
        "trading-controls",
        # Live in a `.platform/services/*.yaml` on origin/main on 2026-10-07 but
        # absent from the inventory. Every one was created AFTER the convention
        # was written (2026-08-04), mostly by copying the `pp-<venue>-*-gw-*`
        # shape of the block above, and none has a proposed name yet. The bare
        # `*` is the all-topics grant in three trader-tools specs.
        "*",
        "oms.halts",
        "pinpredict.odds.pinnacle.props.v1",
        "pp-kalshi-fix-gw-commands",
        "pp-kalshi-fix-gw-signals",
        "pp-kalshi-md-book-shadow",
        "pp-rfq-fills",
        "pp-sxbet-rest-gw-commands",
        "pp-sxbet-rest-gw-signals",
    }
)
