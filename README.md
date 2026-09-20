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
| `check-go-version-sync` | Enforces one Go toolchain pin per repo that every module respects: a `golang` pin outside the repo root is an error, a repo with any `go.mod` must carry a root pin, and every `go.mod` `go` directive must equal it. | `go.mod`, `.tool-versions` |
| `k5s-stack-namespaces` | Fails when two sibling k5s stack overlays declare the same `namespace:`. A new lane is usually a copy of an existing one, and a namespace left unchanged makes `k5s up` server-side-apply over the other lane's objects with no error — Ready pods running a blend of two lanes' config. Asserts uniqueness only, never a naming convention. | `k5s.yaml`, `komp.yaml`, `overlays/*.yaml` |
| `alert-annotation-shape` | Guard the Slack-rendering traps in PrometheusRule annotations: a missing or interpolated `title` (Alertmanager falls back to the raw alertname once two alerts group), an over-long title, a literal-block `description` (Slack keeps the newlines, so the card arrives as ragged half-lines), a paragraph starting with `>` (parsed as a blockquote), and an elapsed time rendered as raw seconds. Every one is valid YAML that renders fine and fails only in Slack. Each check is disablable with `--skip <id>`. | `charts/**/*.yaml` |

## Using a hook

Reference this repo from a consumer's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/pinpredict/pre-commit-hooks
    rev: v0.5.0   # bump to upgrade
    hooks:
      - id: check-go-version-sync
```

**Current release: `v0.8.0`.** Pin an explicit tag rather than a branch;
`pre-commit autoupdate` rewrites the `rev:` to the latest tag when you want to
move.

Each hook's parameters (`files`, `args`, etc.) can be overridden in the
consumer's config the same way as for any third-party hook repo.

### `check-go-version-sync`

The Go toolchain pin is **one per repo, in the root `.tool-versions`**, and
every module must match it:

```
.tool-versions            golang 1.26.6     <- the only legal place
apps/backend-go/go.mod    go 1.26.6
apps/scribe/go.mod        go 1.26.6
chaos/go.mod              go 1.26.6
```

Three things fail the hook: a `golang` line anywhere but the root, a repo that
has a `go.mod` but no root pin, and any module whose `go` directive differs from
the root pin. A nested `.tool-versions` that pins *other* tools
(`golangci-lint`, `nodejs`) is fine — only `golang` is restricted.

**Why root-only.** It used to resolve each module against its nearest ancestor
`.tool-versions` and skip modules that had none. Both halves let drift through
silently. In trader-tools the only pin sat in `apps/backend-go/`, which is not
an ancestor of `apps/scribe/` or `chaos/` — so 2 of 3 modules were checked by
nothing while the hook exited 0. And per-module pins are separate files that
have to be edited together with nothing requiring it; one pin per repo cannot
disagree with itself.

There is **deliberately no opt-out flag**. An escape hatch is exactly what would
let the stale per-module pin back in; a module that genuinely needs a different
toolchain needs a different repo.

⚠️ **The root pin has one known cost, and it is a documentation matter rather
than a reason to nest.** A root `golang` line repoints asdf's shims for every
go-installed tool at that version's GOPATH, so on a box where a tool like
`pre-commit` was itself installed through asdf's Go plugin it can stop
resolving. Install those tools through pipx/uvx/brew instead of asdf's Go
plugin, or `asdf reshim` after changing the pin.

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

### `alert-annotation-shape`

```yaml
  - repo: https://github.com/pinpredict/pre-commit-hooks
    rev: v0.6.0
    hooks:
      - id: alert-annotation-shape
```

A PrometheusRule's `title` and `description` are not documentation — they are
the Slack card a responder reads at 3am. Every trap this catches is invisible in
review: the YAML parses, the chart renders, `promtool` is happy, and the damage
appears only once the alert fires.

The two that cost the most:

- **An interpolated `title`.** Alertmanager renders `.CommonAnnotations.title`
  only when every alert in the group has an identical one, and grouping is by
  alertname — so a title carrying `$labels.venue` silently reverts to the raw
  alertname the moment two instances group. It works in every test and fails
  under load, which is when the card matters most. Per-instance detail belongs
  in `summary`.
- **A literal-block `description`.** Slack preserves newlines, so `|` reproduces
  the source hand-wrapping and the card arrives as a column of ragged
  half-lines. Use `>-` and let Slack reflow to the reader's window. Folding has
  its own rule worth knowing: ONE blank line between paragraphs collapses to a
  single newline, so a visible blank line needs TWO.

Two deliberate choices:

- **It scans text, not parsed YAML.** These are Helm templates, so `{{ ... }}`
  control flow makes most of them invalid YAML — parsing first would skip
  exactly the files that carry the alerts.
- **It scans the whole `--root` (default `charts`), not the staged files.** A
  rule this commit did not touch is just as broken on the card.

`--skip <id>` disables one check (`missing-title`, `interpolated-title`,
`title-length`, `literal-description`, `blockquote-line`, `raw-seconds`), and
`--max-title` moves the 60-char preview limit. The skips exist for adoption: a
repo with a standing backlog can take the other five checks now rather than
waiting until it is clean, since an adopted hook minus one check still guards
five things and an unadopted hook guards nothing. Prefer burning the backlog
down and removing the skip.

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

## `k5s-fragment-parity`

A repo publishing a `kind: Fragment` almost always runs that service itself too,
so there are two definitions of one thing in one repo — and nothing makes them
agree.

They drift immediately. magellan published a fragment pinning all seven collector
intervals to 60s; six minutes later a separate PR removed exactly those overrides
from the repo's own rig, for a measured reason (magellan#651, #652). Both landed
green, and the fragment then told every consumer to do the thing the owner had
just decided against. It was caught by a human reading both files side by side
while preparing an unrelated adoption.

That is the same drift fragments exist to end — except it is *inside* the
publishing repo, where the fragment registry itself cannot help.

```yaml
- repo: https://github.com/pinpredict/pre-commit-hooks
  rev: <sha>
  hooks:
    - id: k5s-fragment-parity
      args:
        # the fragment calls it `magellan`; this repo's own rig calls it `magellan-api`
        - --service=magellan=magellan-api
        # this repo defines it in two lanes, so name the one the fragment mirrors
        - --against=overlays/magellan.yaml
```

What it compares, per fragment service:

- **shared env keys** — a key both sides set must set it to the same value;
- **one-sided keys** — a key only one side sets is reported, which is exactly how
  the interval drift looked.

What it deliberately does not compare:

- **values the fragment parameterizes.** `${input:dbHost}` is not a claim about
  the value, it is a statement that the caller decides, so it cannot drift.
- **owner-vs-consumer differences.** The publishing repo builds from source while
  consumers pull a released image, and placement/sizing belongs to whoever stands
  the rig up — `build`, `image`, `tag`, `namespace`, `replicas`, `resources`,
  `expose`, `readyTimeout`, `dependsOn`, `scheduling`, `localPorts` are ignored by
  default. Extend with `--ignore` rather than weakening the value comparison.

**Ambiguity is an error, not a guess.** If the service is defined in several of
the repo's stack files the hook refuses and names them, because a lane's whole job
is to override its base and comparing against the wrong one reports deliberate
overrides as drift. The first run of this hook against magellan did exactly that —
it picked `overlays/magellan-go.yaml`, a different lane, because `-go` sorts
first. Use `--against`.

It runs on **every** commit, not only when a fragment or overlay changes: the
invariant is a property of the repo, not of the file a commit happens to touch.
Gated on `files:` the check is skipped by any commit that edits neither — which
includes pre-existing drift and, absurdly, the commit that adopts the hook.
magellan#653 added it and went green with `k5s fragment agrees with its own
repo...Skipped`, over a repo that was drifting the whole time.

A repo that publishes no fragment is a clean no-op.
