# pre-commit-hooks docs

Documentation for PinPredict's shared [pre-commit](https://pre-commit.com)
hooks. The repo hosts a small set of hooks centrally so a fix or addition lands
once and every consumer picks it up via a `rev:` bump. Hooks are written in bash
(`language: script`) and python (`language: python`); the manifest
(`.pre-commit-hooks.yaml`) plus the scripts under `hooks/` are the entire
deliverable.

For consumer-facing usage (how to reference a hook, per-hook flags, the
release/tagging process), see the top-level [`README.md`](../README.md). These
docs cover the *internals and the why*.

## How the docs are organized

| Folder | Purpose | When to read |
|---|---|---|
| [`design/`](design/) | Living docs covering the manifest contract, the consumer `rev:` pinning model, local testing, and the rationale for each hook. Each has a `Status:` and `Code:` header pointing at the implementation. | Before adding or editing a hook |

## Design docs

| Topic | Doc |
|---|---|
| The `.pre-commit-hooks.yaml` entry contract, `rev:` pinning, local testing, and per-hook rationale | [`design/hook-contract.md`](design/hook-contract.md) |

## Conventions

- **Status / Code header** at the top of every design doc — `# Design: <Title>`,
  then a `**Status:**` line and a `**Code:**` line pointing at the implementing
  script(s) or manifest.
- **Update the doc in the same PR that changes the code.** Stale design docs
  cost more than missing ones.
- **Design docs are descriptive** ("the hook works like this"); the README is
  the imperative consumer guide ("reference it like this, release like that").
  Don't mix the two — link between them.
