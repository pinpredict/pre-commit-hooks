# Design: the hook contract, `rev:` pinning, and per-hook rationale

**Status:** living document — update in the same PR that changes a hook or the manifest.
**Code:** [`.pre-commit-hooks.yaml`](../../.pre-commit-hooks.yaml), [`hooks/csharpier-worktree-guard.sh`](../../hooks/csharpier-worktree-guard.sh), [`hooks/service-yaml-check.py`](../../hooks/service-yaml-check.py)

## Purpose

Explain how a hook in this repo reaches a consumer, what the manifest entry
promises, how to test a hook locally, and — most importantly — *why* each of the
two current hooks exists. The "why" is the part that doesn't survive in the
source: both hooks encode a specific failure that bit us in production-adjacent
workflows, and a future maintainer needs that context before changing or
removing them.

## The `.pre-commit-hooks.yaml` entry contract

The manifest is a YAML list. Each top-level mapping defines one hook, and it is
the public API every consumer sees. The keys we use:

| Key | Meaning | Notes |
|---|---|---|
| `id` | Identifier consumers reference under `hooks: - id: <id>`. | Renaming = breaking change (major version bump). |
| `name` | Human-readable label in pre-commit output. | Cosmetic. |
| `description` | What the hook does (shown with `--verbose`). | Keep in sync with the README table. |
| `entry` | Command pre-commit runs. | Script paths resolve against **this repo's** clone, e.g. `hooks/csharpier-worktree-guard.sh`. |
| `language` | Execution model. | `script` = run the file directly; `python` = pre-commit builds an isolated venv and installs `additional_dependencies`. |
| `files` | Regex matched against the **consumer's** changed file paths. | `'\.cs$'` for csharpier; `'^\.platform/services/[^/]+\.yaml$'` for service-yaml-check. |
| `additional_dependencies` | Packages installed into the hook's environment. | `service-yaml-check` declares `["pyyaml>=6"]`. Never assume a system install. |
| `args` | Default args appended to `entry`. | Consumers can override in their own config, same as any third-party hook. |
| `pass_filenames` | Whether pre-commit appends matched filenames to the command. | `csharpier-worktree-guard` sets `false` (it walks the tree with `.` itself); `service-yaml-check` leaves it default (it reads paths from `argv`). |
| `require_serial` | Disable per-batch parallelization. | `csharpier-worktree-guard` sets `true` — it runs `csharpier .` once over the whole tree, so parallel batches would be redundant and racy. |

The two entries currently in the manifest:

```yaml
- id: csharpier-worktree-guard
  name: csharpier (worktree-safe)
  entry: hooks/csharpier-worktree-guard.sh
  language: script
  files: '\.cs$'
  pass_filenames: false
  require_serial: true

- id: service-yaml-check
  name: .platform/services/*.yaml static checks
  entry: hooks/service-yaml-check.py
  language: python
  additional_dependencies: ["pyyaml>=6"]
  files: '^\.platform/services/[^/]+\.yaml$'
```

## The consumer `rev:` pinning model

Consumers reference this repo by tag, never by branch:

```yaml
repos:
  - repo: https://github.com/pinpredict/pre-commit-hooks
    rev: v0.1.0   # bump to upgrade
    hooks:
      - id: csharpier-worktree-guard
```

A consumer stays on its pinned `rev:` until it deliberately bumps the tag. That
is the whole point of hosting hooks centrally: a fix lands here once, but it only
reaches a given repo when that repo bumps — so upgrades are explicit, reviewable,
and revertable, and a bad hook change can't silently break every repo at once.

Tags follow semver against the hook *contract*:

- **patch** — internal script change, behavior unchanged.
- **minor** — new hook added, or a new optional flag/env on an existing hook.
- **major** — breaking change to a hook's contract: renamed `id`, changed
  default mode, newly-required env var, changed `entry`, etc.

Release flow: merge the hook change, then `git tag vX.Y.Z && git push origin
vX.Y.Z`. See the README "Releasing" section for the canonical steps.

## Local testing

There is no test suite. Verify a hook the way a consumer would, with
`pre-commit try-repo`, which clones this repo at the current checkout and runs
the named hook. Run it from inside a repo that contains files the hook matches:

```bash
# from a repo with tracked .cs files
pre-commit try-repo /path/to/pre-commit-hooks csharpier-worktree-guard --all-files
# from a repo with a .platform/services/<svc>.yaml
pre-commit try-repo /path/to/pre-commit-hooks service-yaml-check --all-files
```

Plus the static checks: `shellcheck hooks/*.sh` for shell hooks and `python3 -m
py_compile hooks/service-yaml-check.py` for the python hook.

## Why each hook exists

### `csharpier-worktree-guard` — the silent "0 files" no-op in git worktrees

The motivating bug: csharpier 1.x has been observed to walk **0 files** when
invoked from inside a git worktree (a sibling-directory worktree of the main
repo). The tool exits 0, pre-commit reports "Passed", and any formatting issue
that should have been caught locally only surfaces later in CI — after the
commit is already pushed.

The guard runs `dotnet csharpier format .` (or `check .` when
`CSHARPIER_MODE=check`), tees the output, and inspects it: csharpier's
did-nothing lines are stable across the 1.x line —

```
Formatted 0 files in NNNms.
Checked 0 files in NNNms.
```

If it sees `(Formatted|Checked) 0 files` **and** `git ls-files -- '*.cs'` finds
tracked C# files in the consumer tree, it exits 2 with an actionable message
(run from the main working tree, or stage from a `/tmp` copy; reproduce + report
upstream). If csharpier processed files normally, the guard is transparent — it
propagates csharpier's own exit code unchanged. pre-commit invokes it with
`cwd` = consumer repo root, so the `git ls-files` query targets the consumer's
tree as intended.

The actionable failure message *is* the value of this hook. Don't reduce it to a
bare non-zero exit.

### `service-yaml-check` — the post-merge `.platform/services/<svc>.yaml` failures

The motivating bug class: a `.platform/services/<svc>.yaml` self-service deploy
spec can merge looking fine and then fail *after* merge — the chart path doesn't
resolve, the referenced ECR repo / Pod Identity / GHA push-role isn't actually
declared in Terraform, or the NetworkPolicy ingress ports don't match the
chart's health port. These are the failure modes captured in
[platform-gitops#544](https://github.com/pinpredict/platform-gitops/issues/544),
and they're expensive precisely because they pass review and bite at deploy time.

The hook runs a list of static checks over each changed spec:

1. **`chart-path`** — *fully wired*. Resolves `repositories.chart` to
   `<chart>/Chart.yaml` against the consumer repo root; `error` if missing.
2. **`image-repo`** — verify the ECR repo in `repositories.image` exists in TF.
3. **`pod-identity`** — verify a Crossplane PIA / TF entry exists for the SA.
4. **`push-role`** — verify `xp-<svc>-gha-push` is declared in TF.
5. **`netpol-ports`** — cross-check `networkPolicy.ingress` ports against the
   chart's declared health/metrics port.

Checks 2–5 are stubs today: they emit a `!` warning citing #544 rather than
fail, and they're filled in incrementally. The script is deliberately
*informative even with partial inputs* — checks that need an external repo read
its path from `PLATFORM_GITOPS_DIR` / `PLATFORM_INFRA_DIR` and SKIP with a clear
note when it isn't available. Only `error`-level findings set a non-zero exit
(exit code 1); warnings and skips never fail the hook. That keeps the hook
useful as it grows from one real check toward five without ever becoming a
flaky gate.
