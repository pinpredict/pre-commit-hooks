# CLAUDE.md

@AGENTS.md

<!--
AGENTS.md (imported above) is the cross-tool single source of truth for working
in this repo. Keep shared guidance there so Cursor, Copilot, Codex, OpenCode,
and others see it too. This file holds only Claude Code-specific extras.
-->

## Claude Code-specific notes

- **Subagents** (`.claude/agents/`):
  - `hook-author` — author or modify a pre-commit hook here: the `.pre-commit-hooks.yaml` entry contract, the two existing hooks, the consumer `rev:` pinning model, and local testing with `pre-commit try-repo . <hook-id>`.
- **Slash commands** (`.claude/commands/`):
  - `/check` — run the repo's local verification: `pre-commit run --all-files`, `shellcheck hooks/*.sh`, and `python3 -m py_compile` on the python hook, then summarize.
