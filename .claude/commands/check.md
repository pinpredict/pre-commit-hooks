---
description: Run this repo's local verification — pre-commit, shellcheck, and a python syntax check — and summarize the results.
allowed-tools: Bash(pre-commit run:*), Bash(pre-commit try-repo:*), Bash(shellcheck:*), Bash(python3:*), Bash(git status:*), Bash(git diff:*), Read
---

Run the local checks for this repo and report what passed and what failed. There
is no `Makefile` and no test suite here, so the checks below are the full
verification surface.

1. **pre-commit** — `pre-commit run --all-files`. This runs whatever hooks this
   repo configures on itself (trailing-whitespace, end-of-file-fixer,
   check-yaml, etc., if a `.pre-commit-config.yaml` is present). If the repo has
   no `.pre-commit-config.yaml`, say so and skip — do not invent hooks.
2. **shellcheck** — `shellcheck hooks/*.sh`. The shell hooks must be clean. Report
   every finding with its `SC` code; these are real and should be fixed, not
   suppressed without reason.
3. **python syntax** — `python3 -m py_compile hooks/service-yaml-check.py` (and
   any other `hooks/*.py`). This catches syntax/import-time errors only; there is
   no behavioral test suite. If `ruff` is available, also run
   `ruff check hooks/*.py` and include its findings; if it is not installed, note
   that and move on — do not install it.

To exercise a hook end-to-end (not just lint it), use
`pre-commit try-repo . <hook-id> --all-files` from inside a repo that has
matching files (`.cs` files for `csharpier-worktree-guard`, a
`.platform/services/<svc>.yaml` for `service-yaml-check`).

Summarize at the end: which checks ran, pass/fail per check, and a short list of
any findings with the file and line. Do not fix anything unless asked — this
command reports.
