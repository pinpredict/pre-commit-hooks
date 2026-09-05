#!/usr/bin/env python3
"""Guard the Slack-rendering traps in PrometheusRule annotations.

A rule's `title` and `description` are not documentation. They are the Slack
card a responder reads at 3am, and every trap below is invisible in review —
the YAML is valid, the chart renders, `promtool` is happy, and the damage only
appears in Slack once the alert actually fires.

1. A missing `title` (`missing-title`).
   The Alertmanager Slack template renders `.CommonAnnotations.title` and falls
   back to the raw alertname, so an untitled rule pages as
   `TraderToolsBackendUpstreamErrorRateHigh` — a symbol, not a sentence.

2. A `title` containing `{{` (`interpolated-title`).
   Alertmanager populates `.CommonAnnotations.title` ONLY when every alert in
   the group has an identical one. Grouping is by alertname, so a title
   interpolating a label or `$value` silently falls back to the alertname the
   moment two instances group — the exact failure the annotation exists to
   prevent, appearing only under load. Per-instance detail belongs in `summary`.

3. A `title` over `--max-title` chars (`title-length`).
   Slack truncates notification previews.

4. A `description` that is a LITERAL block (`literal-description`).
   Slack preserves newlines, so a literal block reproduces the source
   hand-wrapping verbatim and the card arrives as a column of ragged half-lines:

       The order-group update stream is the ONLY way a trip becomes
       knowable — Kalshi exposes no read for a group's triggered
       state or its rolling volume, and it has produced no frame,

   Use a folded block (`>-`). Slack then reflows each paragraph to the reader's
   window. Note the folding rules: ONE blank line between prose paragraphs
   collapses to a single newline, so use TWO for a visible blank line; a list
   block indented two further spaces keeps one line per item, and needs only one
   blank line on each side.

5. A description paragraph that STARTS with `>` (`blockquote-line`).
   Slack parses a line-initial `>` as a blockquote: the character is eaten and
   the neighbouring lines are joined without a space, so "has been\n>1000ms"
   renders as "has been1000ms" — which reads as a CURRENT VALUE rather than a
   threshold breach.

6. An elapsed time rendered as raw seconds (`raw-seconds`).
   `{{$value | printf "%.0f"}}s` puts `23845s` on the card, and a responder has
   to divide before they know whether that is a blip or most of a day.
   Prometheus templates annotations at rule-evaluation time, so
   `humanizeDuration` is available and renders `6h 37m 25s`. For a Helm-side
   threshold use `duration (int64 .Values…)` — note `int` does NOT work,
   sprig's cast yields `0s` for a plain int and only `int64`/`toString`
   round-trip correctly.

Scans TEXT, not parsed YAML, and that is deliberate: these files are Helm
templates, so `{{ ... }}` control flow makes most of them invalid YAML. Parsing
first would mean skipping exactly the files that carry the alerts.

Checks the whole tree under `--root` rather than the staged files, because a
rule this commit did not touch is just as broken on the card. Every check can be
turned off with `--skip <id>` so a repo with a standing backlog can adopt the
remaining checks now instead of waiting until it is clean — an adopted hook
minus one check still guards five things; an unadopted hook guards nothing.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ._common import emit

PROG = "alert-annotation-shape"

ALERT_SPLIT = re.compile(r"\n(?=\s*- alert:)")
ALERT_NAME = re.compile(r"-\s*alert:\s*(\S+)")
HELM_CONTROL = re.compile(r"^\s*\{\{-?\s*(if|else|end|range|with|define|/\*)")
DESCRIPTION = re.compile(r"^(\s*)description:\s*(\|-?|>-?)", re.M)
TITLE = re.compile(r"^\s*title:\s*(.+)$", re.M)

CHECKS = (
    "missing-title",
    "interpolated-title",
    "title-length",
    "literal-description",
    "blockquote-line",
    "raw-seconds",
)

DEFAULT_MAX_TITLE = 60


def description_lines(block: str):
    """Yield (style, is_paragraph_start, line) for the description block, if any."""
    match = DESCRIPTION.search(block)
    if not match:
        return
    indent, style = len(match.group(1)), match.group(2)[0]
    at_start = True
    for line in block[match.end() :].split("\n")[1:]:
        # Helm control lines are scaffolding, not prose the reader ever sees.
        if HELM_CONTROL.match(line):
            continue
        if not line.strip():
            at_start = True
            continue
        # Dedent to the key's own column ends the block scalar.
        if len(line) - len(line.lstrip()) <= indent:
            break
        yield style, at_start, line
        at_start = False


def raw_second_renders(block: str):
    """Yield snippets where an interpolated duration is followed by a literal `s`.

    Matches both shapes: a Prometheus `$value` piped through printf, and a Helm
    value named `…Seconds`. Anything else ending `}}s` is a plural, not a unit.
    """
    for idx in range(len(block) - 3):
        if block[idx : idx + 3] != "}}s":
            continue
        if idx + 3 < len(block) and block[idx + 3].isalpha():
            continue
        lookback = block[max(0, idx - 80) : idx]
        if "$value" in lookback or "Seconds" in lookback:
            yield block[max(0, idx - 60) : idx + 3].strip()


def check_block(path: Path, block: str, enabled: set[str], max_title: int) -> list[str]:
    """Return every problem in one `- alert:` block."""
    name_match = ALERT_NAME.search(block)
    if not name_match:
        return []
    name = name_match.group(1)
    problems = []

    titles = TITLE.findall(block)
    if not titles and "missing-title" in enabled:
        problems.append(
            f"{path}: {name}: no `title` annotation. The Slack card falls back to the "
            f"raw alertname, so this pages as {name!r} instead of a sentence."
        )
    for title in titles:
        title = title.strip().strip("'\"")
        if "{{" in title and "interpolated-title" in enabled:
            problems.append(
                f"{path}: {name}: `title` interpolates ({title!r}). It must be static — "
                "Alertmanager only renders .CommonAnnotations.title when every alert in "
                "the group agrees, so this falls back to the alertname once two group."
            )
        if len(title) > max_title and "title-length" in enabled:
            problems.append(
                f"{path}: {name}: `title` is {len(title)} chars (max {max_title}); "
                "Slack truncates notification previews."
            )

    for style, at_start, line in description_lines(block):
        if style == "|":
            if "literal-description" in enabled:
                problems.append(
                    f"{path}: {name}: `description` is a literal block (`|`). Slack keeps "
                    "the newlines, so the card renders the source hand-wrapping as ragged "
                    "half-lines. Use `>-` and separate paragraphs with a blank line."
                )
            # The style is a property of the block, so one report settles it.
            break
        if at_start and line.lstrip().startswith(">") and "blockquote-line" in enabled:
            problems.append(
                f"{path}: {name}: description paragraph starts with '>' "
                f"({line.strip()[:60]!r}). Slack reads that as a blockquote, drops the "
                "'>' and joins the neighbouring lines. Rewrap so it follows a word."
            )

    if "raw-seconds" in enabled:
        for snippet in raw_second_renders(block):
            problems.append(
                f"{path}: {name}: renders an elapsed time as raw seconds ({snippet!r}). "
                "The card then reads '23845s' and the responder has to do the division. "
                "Use `humanizeDuration` for $value, or `duration (int64 …)` for a Helm "
                "value — `int` yields '0s'."
            )

    return problems


def check(roots: list[Path], enabled: set[str], max_title: int) -> list[str]:
    """Scan every alert-bearing YAML under each root."""
    problems: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.y*ml")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "- alert:" not in text:
                continue
            for block in ALERT_SPLIT.split(text):
                problems.extend(check_block(path, block, enabled, max_title))
    return problems


def main(argv: list[str] | None = None) -> int:
    # Defaulted so setuptools can wire this as a console script while a direct
    # `python -m` invocation still works.
    parser = argparse.ArgumentParser(prog=PROG, description=__doc__)
    parser.add_argument(
        "--root",
        action="append",
        default=None,
        help="directory to scan (repeatable; default: charts)",
    )
    parser.add_argument(
        "--max-title",
        type=int,
        default=DEFAULT_MAX_TITLE,
        help=f"longest title Slack shows in a preview (default: {DEFAULT_MAX_TITLE})",
    )
    parser.add_argument(
        "--skip",
        action="append",
        choices=CHECKS,
        default=[],
        metavar="CHECK",
        help=f"disable one check (repeatable): {', '.join(CHECKS)}",
    )
    # pre-commit appends the changed files when a consumer overrides
    # pass_filenames; they are ignored on purpose — see the module docstring.
    parser.add_argument("filenames", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    roots = [Path(r) for r in (args.root or ["charts"])]
    enabled = set(CHECKS) - set(args.skip)

    problems = check(roots, enabled, args.max_title)
    if problems:
        emit(problems, PROG)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
