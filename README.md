# pinpredict/pre-commit-hooks

Shared [pre-commit](https://pre-commit.com) hooks used across PinPredict
repositories. Hosted here so a fix or addition lands once and is picked up by
every consumer via a `rev:` bump rather than copying the same script into N
repos.

## Available hooks

| id | What | Triggers on |
|---|---|---|
| `csharpier-worktree-guard` | Run `dotnet csharpier format .` (or `check .` via `CSHARPIER_MODE=check`) but fail loudly if csharpier reports "0 files" while the repo actually contains tracked `.cs` files. Catches the silent no-op observed when csharpier runs from inside a git worktree. | `*.cs` |

## Using a hook

Reference this repo from a consumer's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/pinpredict/pre-commit-hooks
    rev: v0.1.0   # bump to upgrade
    hooks:
      - id: csharpier-worktree-guard
```

Each hook's parameters (`files`, `args`, etc.) can be overridden in the
consumer's config the same way as for any third-party hook repo.

### `csharpier-worktree-guard`

Defaults to `format` mode. Switch to `check` (CI-friendly, no in-place
changes) via the `CSHARPIER_MODE` env var:

```yaml
- id: csharpier-worktree-guard
  args: []
  # set in CI via env:  CSHARPIER_MODE=check
```

Requires `dotnet csharpier` on `PATH` in the environment running pre-commit
(same requirement as the plain csharpier hook).

## Releasing

Cut a tag when a hook changes:

```bash
git tag v0.2.0
git push origin v0.2.0
```

Consumers don't move until they bump their `rev:` — keeps changes explicit
and revertable. Tags follow semver:

- **patch** — internal script change, behaviour unchanged
- **minor** — new hook added, or new optional flag on an existing hook
- **major** — breaking change to a hook's contract (entry, default mode,
  required env, etc.)

## Adding a new hook

1. Drop the script in `hooks/<hook-id>.sh` (or another language — pre-commit
   supports `language: script` / `python` / `golang` / etc.).
2. Add an entry to `.pre-commit-hooks.yaml` with `id`, `name`,
   `description`, `entry`, `language`, `files`, and any other relevant
   keys. See the [pre-commit docs](https://pre-commit.com/#creating-new-hooks)
   for the full schema.
3. Update this README's "Available hooks" table.
4. Open a PR. After merge, cut a tag.

## Why this repo exists

Pre-commit hooks defined as `repo: local` in a `.pre-commit-config.yaml` are
quick to add but duplicate across repos, drift over time, and don't have a
clear ownership story. Once a hook fits more than one repo — or once it
encodes platform-wide policy (commit-message format, no raw-`terraform`,
account-id hardcoding) — it belongs here so a fix flows everywhere via a
version bump.
