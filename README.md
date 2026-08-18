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
| `stevedore-release-scope` | Assert that onboarding or retiring a service does not widen the shared image build contract: named services pair an `.stevedore.yaml` image id with a name-matching sibling chart, `docker-release` and `chart-release` receive the same `only:` selector, and `change_detection.shared_paths` carries the all-image signal without listing paths every onboarding touches. | `.stevedore.yaml`, `.github/workflows/ci.yml`, `charts/*/Chart.yaml` |
| `no-production-newtonsoft` | Reject Newtonsoft.Json references in production .NET sources: a case-insensitive scan of every tracked source and build file, permitted only under the `--allow-prefix` paths (the approved test/benchmark projects) and on the one central `PackageVersion` line. Static half only — the transitive package-graph half needs `dotnet restore` and stays in the consumer's CI. | every commit (whole-tree scan) |
| `check-go-version-sync` | Fails when a `go.mod` `go` directive and the governing `.tool-versions` `golang` pin drift apart. | `go.mod`, `.tool-versions` |
| `k5s-stack-namespaces` | Fails when two sibling k5s stack overlays declare the same `namespace:`. A new lane is usually a copy of an existing one, and a namespace left unchanged makes `k5s up` server-side-apply over the other lane's objects with no error — Ready pods running a blend of two lanes' config. Asserts uniqueness only, never a naming convention. | `k5s.yaml`, `komp.yaml`, `overlays/*.yaml` |

## Using a hook

Reference this repo from a consumer's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/pinpredict/pre-commit-hooks
    rev: v0.5.0   # bump to upgrade
    hooks:
      - id: check-go-version-sync
```

**Current release: `v0.5.0`.** Pin an explicit tag rather than a branch;
`pre-commit autoupdate` rewrites the `rev:` to the latest tag when you want to
move.

Each hook's parameters (`files`, `args`, etc.) can be overridden in the
consumer's config the same way as for any third-party hook repo.

### `csharpier-worktree-guard`

No repo currently consumes this hook — it's available but unwired, so treat
changes to it as unexercised in practice.

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
and running `pre-commit run service-yaml-check --all-files` in CI. To invoke
it outside pre-commit, install this repo and call the `service-yaml-check`
console script (`pinpredict_hooks/service_yaml_check.py`) with the paths —
there is no `hooks/service-yaml-check.py` to run directly, for the packaging
reason spelled out under [Repository layout](#repository-layout).

### `k5s-stack-namespaces`

```yaml
  - repo: https://github.com/pinpredict/pre-commit-hooks
    rev: v0.5.0
    hooks:
      - id: k5s-stack-namespaces
```

No arguments. A k5s rig is a base stack plus lane overlays
(`k5s up -f overlays/perf-10x.yaml`), and a lane targeting a shared cluster
declares its own `namespace:` so bringing one lane up cannot converge the rig
another lane is standing in.

What it catches is quiet: a new lane starts as a copy of an existing one, and if
its `namespace:` is not changed with everything else, `k5s up` server-side-applies
over the old lane's objects. Nothing errors — the pods are Ready and the rig is
running a blend of two lanes' configuration. For a perf rig that means every
number it reports was measured against a universe nobody described.

Two deliberate choices:

- **Uniqueness only, never a naming convention.** A repo's lane names are its own
  business; pinning a pattern like `perf-rig-<lane>` would be one repo's
  convention wearing an org hook's clothes.
- **Files are read as written, not through k5s's `extends:` resolution.** Two
  lanes that both *restate* a shared namespace is the collision; resolving first
  would hide it. An overlay that declares no namespace at all — inheriting the
  base stack's, the normal shape for a lane that only adjusts load — is skipped.

It compares every stack in the changed files' **directories**, not just the
changed set: a collision is a property of the whole set, and the lane that already
owned the namespace is usually not part of the commit that collides with it.

## Releasing

Bump the version in `pyproject.toml` **in the same PR as the hook change**,
then cut the matching tag:

```bash
# 1. edit pyproject.toml:  version = "0.4.0"   (must match the tag)
git tag v0.4.0
git push origin v0.4.0
```

The `pyproject.toml` version is what consumers actually pip-install under
`language: python`, so a tag cut without the bump ships a package whose
self-reported version disagrees with the `rev:` it came from — confusing to
debug and invisible until someone checks. Keep the two in lockstep.

Consumers don't move until they bump their `rev:` — keeps changes explicit
and revertable. Tags follow semver:

- **patch** — internal script change, behaviour unchanged
- **minor** — new hook added, or new optional flag on an existing hook
- **major** — breaking change to a hook's contract (entry, default mode,
  required env, etc.)

## Repository layout

| Path | What |
|---|---|
| `pinpredict_hooks/` | Python hooks, shipped as console scripts via `pyproject.toml` |
| `hooks/` | Shell hooks (`language: script`), run directly from the repo |
| `tests/` | Unit tests for the Python hooks — `python -m unittest discover -s tests` |
| `.github/workflows/ci.yml` | CI: runs the unit tests plus the `hook-install` job that exercises the pre-commit install path |

**Python hooks must be console scripts.** pre-commit's `language: python`
pip-installs this repo and then runs the hook's `entry` as a *command*, so a
repo-relative path entry (`hooks/foo.py`) cannot work. Every Python hook needs
an entry in `[project.scripts]` and an `entry:` matching that script name.
Getting this wrong fails at install time for every consumer with
`Directory '.' is not installable` — `service-yaml-check` shipped that way and
was never runnable anywhere until it was fixed. The `hook-install` CI job now
exercises the install path for exactly this reason.

Shell hooks stay in `hooks/` with `language: script`; they need no packaging.

## Adding a new hook

1. Python: add a module under `pinpredict_hooks/` with a `main(argv=None) -> int`
   and register it in `[project.scripts]`. Shell: drop the script in
   `hooks/<hook-id>.sh` and use `language: script`.
2. Add an entry to `.pre-commit-hooks.yaml` with `id`, `name`,
   `description`, `entry`, `language`, `files`, and any other relevant
   keys. See the [pre-commit docs](https://pre-commit.com/#creating-new-hooks)
   for the full schema.
3. Add tests under `tests/`. Keep them file-based and free of `git`/subprocess
   work so the suite stays fast enough to run as a hook itself.
4. Update this README's "Available hooks" table.
5. Open a PR. After merge, cut a tag.

## `stevedore-release-scope`

Every assertion is opt-in via args, so the hook fits repos that have only some
of the surfaces — a repo with no `chart-release` job, or no
`change_detection.shared_paths` key, skips those checks instead of failing.
A repo with no `.stevedore.yaml` at all is a clean no-op.

```yaml
- repo: https://github.com/pinpredict/pre-commit-hooks
  rev: v0.5.0
  hooks:
    - id: stevedore-release-scope
      args:
        - --service=nadex-rfqgw
        - --require-shared-path=Directory.Build.props
        - --forbid-shared-path=Dockerfile
        - --forbid-shared-path=.dockerignore
        - --forbid-shared-path=*.sln
```

| Flag | Purpose |
|---|---|
| `--service ID` (repeatable) | `ID` is an image id in `.stevedore.yaml` **and** `charts/ID/Chart.yaml` declares `name: ID` |
| `--require-shared-path P` (repeatable) | `change_detection.shared_paths` must contain `P` |
| `--forbid-shared-path P` (repeatable) | `change_detection.shared_paths` must **not** contain `P` |
| `--expect-selector EXPR` | both release jobs pass exactly this `only:` expression |
| `--docker-job` / `--chart-job` | job names to compare (default `docker-release` / `chart-release`) |
| `--catalog` / `--workflow` / `--charts-dir` | override the default paths |

Note that the manual-dispatch selector expression is **not** uniform across the
org — most repos map `services: all` to an empty selector, while `trading` maps
it to `all` on purpose. Pin `--expect-selector` only when a repo wants its own
variant frozen; the docker/chart consistency check runs either way.

All violations are collected and reported in one run rather than failing on the
first, so a single `pre-commit run` shows the whole picture.

## `no-production-newtonsoft`

Production .NET code should use `System.Text.Json`; a `Newtonsoft.Json`
reference is allowed only in explicitly approved test and benchmark projects.
Nothing is exempt by default — name every permitted prefix:

```yaml
- repo: https://github.com/pinpredict/pre-commit-hooks
  rev: v0.5.0
  hooks:
    - id: no-production-newtonsoft
      args:
        - --allow-prefix=PinPredict.Tests/
        - --allow-prefix=PinPredict.ParlayManager.Tests/
        - --allow-prefix=PinPredict.Benchmarks/
        - --central-version-file=Directory.Packages.props
```

| Flag | Purpose |
|---|---|
| `--allow-prefix PREFIX` (repeatable) | path prefix where a reference is permitted; nothing is allowed by default |
| `--central-version-file PATH` | the one file permitted to declare the package's central `PackageVersion` |
| `--token TOKEN` | case-insensitive token that marks a violation (default `newtonsoft`) |
| `--package ID` | package id for the central-version exemption (default `<token>.Json`) |
| `--source-glob GLOB` (repeatable) | git pathspecs to scan (default `*.cs *.csproj *.props *.targets`) |
| `--root PATH` | repository root to scan (default the working directory) |

**This is the static half of the policy only.** Catching Newtonsoft that arrives
*transitively* needs `dotnet list package --include-transitive`, which needs
`dotnet restore` and the solution's private feed credentials — far too slow and
too credential-bound for a commit hook. Keep that guard in your own CI beside
the SDK install; this hook covers the direct references, which are the ones a
commit actually introduces.

Two contract details worth knowing before you tune it:

- **The scan is whole-tree, not staged-files.** Files come from `git ls-files`
  and the hook runs `pass_filenames: false` / `always_run: true`. The policy is a
  property of the repository, so a violation sitting in a file your commit never
  touched must still fail — scoping to changed files would let a pre-existing
  reference stay invisible forever.
- **The central-version exemption is scoped to one named file.** A
  `PackageVersion` element copied into an ordinary project file is still a
  violation, so the exemption can't be used to smuggle a reference in.

## Why this repo exists

Pre-commit hooks defined as `repo: local` in a `.pre-commit-config.yaml` are
quick to add but duplicate across repos, drift over time, and don't have a
clear ownership story. Once a hook fits more than one repo — or once it
encodes platform-wide policy (commit-message format, no raw-`terraform`,
account-id hardcoding) — it belongs here so a fix flows everywhere via a
version bump.

## check-go-version-sync

Fails when a `go.mod` `go` directive and the governing `.tool-versions`
`golang` pin drift apart — they must match so local (asdf) and CI build the
same toolchain. Each module's governing pin is the nearest ancestor
`.tool-versions` with a `golang` line, so nested modules
(`apps/<svc>/go.mod`) work; modules without a governing pin are skipped.

```yaml
- repo: https://github.com/pinpredict/pre-commit-hooks
  rev: v0.5.0
  hooks:
    - id: check-go-version-sync
```
