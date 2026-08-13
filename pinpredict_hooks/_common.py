#!/usr/bin/env python3
"""Helpers shared by the Python hooks in this repo.

Private module — not exposed as a console script. Everything here is behavior
that every hook needs to get identically right: reading an optional YAML file,
and reporting failures so GitHub Actions annotates them while a local terminal
stays readable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Distinguishes "the file is not there" from "the file parsed to None". A hook
# must treat an absent surface as a clean no-op but an empty one as a real
# (checkable) document — collapsing both to None loses that.
MISSING = object()


def load_yaml(path: Path, prog: str) -> Any:
    """Parse `path`, returning MISSING when the file does not exist.

    A malformed document is fatal rather than a skipped check: silently passing
    on unparseable YAML is how a guard stops guarding without anyone noticing.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return MISSING
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise SystemExit(f"{prog}: {path} is not valid YAML: {error}")


def emit(failures: list[str], label: str) -> None:
    """Print each failure, as a GHA annotation under Actions and plainly elsewhere."""
    prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") == "true" else "ERROR: "
    for failure in failures:
        print(f"{prefix}{label}: {failure}")
