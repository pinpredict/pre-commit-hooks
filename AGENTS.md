# AGENTS.md — pre-commit-hooks

Guidance for AI coding agents (Claude Code, Cursor, Copilot, Codex, OpenCode, …) working in this repository. This is the **cross-tool single source of truth** — `CLAUDE.md` imports it.

## Project Overview

Shared [pre-commit](https://pre-commit.com) hooks used across PinPredict repositories. Hosted centrally so a fix or addition lands once and every consumer picks it up via a `rev:` bump rather than copying the same script into N repos.

Hooks are written in **bash** (`language: script`) and **python** (`language: python`). There is no compiled toolchain — the manifest (`.pre-commit-hooks.yaml`) and the scripts under `hooks/` are the entire deliverable. Consumers reference the repo from their own `.pre-commit-config.yaml`, pinned to a tag.

## Quick Reference

```bash
# Run a hook against the current tree the way a consumer's pre-commit would.
# `try-repo` clones THIS repo at the current checkout and runs the named hook;
# run it from inside a repo that has matching files (e.g. a repo with .cs files
# for csharpier-worktree-guard, or a .platform/services/*.yaml for the other).
pre-commit try-repo /Users/bhamilton/Developer/github.com/pinpredict/pre-commit-hooks csharpier-worktree-guard --all-files
pre-commit try-repo /Users/bhamilton/Developer/github.com/pinpredict/pre-commit-hooks service-yaml-check --all-files

# Lint the shell hooks.
shellcheck hooks/*.sh

# Syntax-check the python hook (it has no test suite).
python3 -m py_compile hooks/service-yaml-check.py

# Run the python hook directly (it accepts file paths as argv).
python3 hooks/service-yaml-check.py path/to/.platform/services/<svc>.yaml
```

There is no `Makefile` and no test suite in this repo — the commands above are the full local-verification surface. Validate behavior with `pre-commit try-repo` against a real consumer tree.

## Project Structure

- `.pre-commit-hooks.yaml` — the hook manifest. This is what consumers reference; each top-level entry defines one hook (`id`, `name`, `description`, `entry`, `language`, `files`, and any per-hook keys). Editing an entry changes the contract every consumer sees on their next `rev:` bump.
- `hooks/csharpier-worktree-guard.sh` — bash wrapper around `dotnet csharpier format .` (or `check .`).
- `hooks/service-yaml-check.py` — python static checker for `.platform/services/<svc>.yaml`.
- `README.md` — consumer-facing usage, the available-hooks table, and the release/tagging process.
- `docs/` — design notes (the entry contract, the `rev:` pinning model, and the per-hook rationale). See [Documentation](#documentation).

## Code Conventions

- **Shell hooks pass `shellcheck`.** `csharpier-worktree-guard.sh` runs under `set -euo pipefail`; keep that discipline.
- **Python hooks** target the python the consumer's pre-commit provides; declare runtime deps via `additional_dependencies` in the manifest (e.g. `service-yaml-check` declares `pyyaml>=6`), never assume a system install.
- **en-US spelling** in all code, comments, and messages (`behavior`, not `behaviour`; `color`, not `colour`).
- Keep a hook's user-facing failure message actionable — the value of `csharpier-worktree-guard` is its explanation + workaround, not just a non-zero exit.

## Hooks

| id | What | Triggers on |
|---|---|---|
| `csharpier-worktree-guard` | Runs `dotnet csharpier format .` (or `check .` via `CSHARPIER_MODE=check`) but fails loudly if csharpier reports "0 files" while the repo actually contains tracked `.cs` files. Catches the silent no-op observed when csharpier runs from inside a git worktree. | `*.cs` |
| `service-yaml-check` | Static checks for new/changed `.platform/services/<svc>.yaml` files. The wired check is `chart-path` (resolves `repositories.chart` against the consumer tree); `image-repo`, `pod-identity`, `push-role`, and `netpol-ports` emit a `!` warning citing platform-gitops#544 and are filled in incrementally. | `.platform/services/*.yaml` |

The block-by-block manifest contract, the consumer `rev:` pinning model, and the rationale for each hook live in [`docs/design/hook-contract.md`](docs/design/hook-contract.md). Read it before adding or editing a hook.

### Adding a hook

1. Drop the script in `hooks/<hook-id>.sh` (or `.py`, etc. — pre-commit supports `language: script` / `python` / `golang`).
2. Add an entry to `.pre-commit-hooks.yaml` (`id`, `name`, `description`, `entry`, `language`, `files`, plus any other keys). See the [pre-commit docs](https://pre-commit.com/#creating-new-hooks).
3. Update the README "Available hooks" table and the [Hooks](#hooks) table above.
4. Open a PR. After merge, cut a tag — consumers don't move until they bump their `rev:`.

## Documentation

In-depth notes live in `docs/` — see [`docs/README.md`](docs/README.md) for the index.

- [`docs/design/hook-contract.md`](docs/design/hook-contract.md) — the `.pre-commit-hooks.yaml` entry contract, the consumer `rev:` pinning model, local testing, and the *why* behind each of the two current hooks.

Each design doc carries a `Status:` line and a `Code:` line pointing at the implementation. If you change a hook, update its doc in the same PR — stale design docs cost more than missing ones.
