#!/usr/bin/env bash
# Wrapper around `dotnet csharpier format .` that fails loudly when csharpier's
# directory walker silently reports "Formatted 0 files" / "Checked 0 files"
# while the repo actually contains C# files.
#
# Why: csharpier 1.x has been observed to find 0 files when invoked from
# inside a git worktree (sibling-directory worktree of the main repo). The
# tool exits 0, the pre-commit hook reports "Passed", and formatting issues
# that would otherwise be caught locally only surface in CI. This guard
# makes that condition fail fast at commit time.
#
# Behaviour:
#   - Run `dotnet csharpier format .` (or `check .` if CSHARPIER_MODE=check).
#   - If output reports "0 files" but `git ls-files '*.cs'` finds tracked C#
#     files in the consumer repo, exit 2 with a clear message.
#   - Otherwise, propagate csharpier's exit code unchanged.
#
# Pre-commit invokes this with cwd = consumer repo root and the script path
# resolved against this repo's clone, so the `git ls-files` call queries the
# consumer's tree as intended.

set -euo pipefail

mode="${CSHARPIER_MODE:-format}"

output_file=$(mktemp -t csharpier-worktree-guard.XXXXXX)
trap 'rm -f "$output_file"' EXIT

set +e
dotnet csharpier "$mode" . 2>&1 | tee "$output_file"
csharpier_status=${PIPESTATUS[0]}
set -e

# csharpier's "did nothing" lines are stable across the 1.x line:
#   "Formatted 0 files in NNNms."
#   "Checked 0 files in NNNms."
if grep -qE '(Formatted|Checked) 0 files' "$output_file"; then
    cs_count=$(git ls-files -- '*.cs' 2>/dev/null | wc -l | tr -d ' ')
    if [ "${cs_count:-0}" -gt 0 ]; then
        cat <<EOF >&2

==============================================================================
csharpier-worktree-guard: csharpier processed 0 files but the repo contains
${cs_count} tracked .cs file(s). This is the silent-no-op behaviour observed
when running csharpier from inside a git worktree — the tool exits 0 without
checking anything, so the pre-commit hook would otherwise report "Passed"
and CI catches the formatting issue downstream.

Workarounds, easiest first:
  - Run the same operation from the main repo working tree, or stage from a
    /tmp copy:  cp <file>.cs /tmp/ && (cd <main-repo> && dotnet csharpier check /tmp)
  - Reproduce + report upstream:
    https://github.com/belav/csharpier/issues (include the worktree shape)

Failing this hook so the formatting issue doesn't reach CI.
==============================================================================
EOF
        exit 2
    fi
fi

exit "$csharpier_status"
