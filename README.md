# pinpredict/pre-commit-hooks

Shared [pre-commit](https://pre-commit.com) hooks used across PinPredict
repositories. Hosted here so a fix or addition lands once and is picked up by
every consumer via a `rev:` bump rather than copying the same script into N
repos.

## Available hooks

| id | What | Triggers on |
|---|---|---|
| `csharpier-worktree-guard` | Run `dotnet csharpier format .` (or `check .` via `CSHARPIER_MODE=check`) but fail loudly if csharpier reports "0 files" while the repo actually contains tracked `.cs` files. Catches the silent no-op observed when csharpier runs from inside a git worktree. | `*.cs` |
| `service-yaml-check` | Static checks for new/changed `.platform/services/<svc>.yaml` files: chart path resolves, ECR repo / PIA / GHA push-role exist in TF, networkPolicy ingress ports match the chart's declared health port. Catches the post-merge failure modes from [platform-gitops#544](https://github.com/pinpredict/platform-gitops/issues/544). | `.platform/services/*.yaml` |

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

### `service-yaml-check`

Stub. Currently the only fully-wired check is `chart-path` (resolves
`repositories.chart` against the consumer repo's tree). The remaining
checks emit a `!` warning citing platform-gitops#544 and will be filled
in incrementally:

- `image-repo` — verify the ECR repo exists in TF (or is added by a paired PR).
- `pod-identity` — verify a Crossplane PIA / TF entry exists for the SA.
- `push-role` — verify `xp-<svc>-gha-push` is declared in TF.
- `netpol-ports` — cross-check ingress ports against the chart's defaults.

Optional env vars (used by the not-yet-implemented checks):

| var | purpose |
|---|---|
| `PLATFORM_GITOPS_DIR` | path to a `platform-gitops` checkout, for PIA / Crossplane lookups |
| `PLATFORM_INFRA_DIR`  | path to a `platform-infrastructure` checkout, for TF role / ECR lookups |

Wire into CI by adding to the consumer repo's `.pre-commit-config.yaml`
and running `pre-commit run service-yaml-check --all-files` in CI, or by
calling `hooks/service-yaml-check.py <paths>` directly.

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
