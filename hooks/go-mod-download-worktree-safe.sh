#!/usr/bin/env bash
# Download every Go module's dependencies with git's repository variables
# cleared, BEFORE the Go hooks run, so that no fetch made during a commit can
# re-initialize the repository being committed to as a bare repository.
#
# The failure. A commit made in a linked worktree runs its hooks with
# GIT_DIR=<repo>/.git/worktrees/<name> exported (a commit in the primary
# checkout exports none). When a Go hook (go mod tidy, golangci-lint) is the
# first thing to fetch a module over git — a private module under GOPRIVATE,
# which skips the proxy — Go begins with `git init --bare` in
# $GOMODCACHE/cache/vcs/<hash>, and that one command does not override GIT_DIR.
# It inherits the worktree's, so git re-initializes the worktree's repository
# instead of creating the cache, and writes `core.bare = true` into the SHARED
# .git/config. Linked worktrees ignore that key, so nothing looks wrong where
# the commit ran; the primary checkout's `git status` fails with
# "fatal: this operation must be run in a work tree". The hook itself fails with
#
#   git remote add origin -- <url> in <GOMODCACHE>/cache/vcs/<hash>: exit status 128:
#   fatal: not a git repository: '<GOMODCACHE>/cache/vcs/<hash>'
#
# because Go does pass GIT_DIR explicitly to every git command after the init.
# The code is newGitRepo in Go's src/cmd/go/internal/modfetch/codehost/git.go,
# unchanged on Go master as of 2026-10-21. It broke magellan's primary checkout
# on 2026-10-20: two commits from sibling worktrees failed go-mod-tidy with the
# error above, and .git/config gained `bare = true` four seconds into the second.
#
# The fix. Run `go mod download` in every module (each go.mod, found the way
# check-go-version-sync finds them) with git's repo-local variables cleared.
# That fetches what the Go hooks would, and creates the module cache's git
# repositories where Go means them to be. Once one exists, Go addresses it by
# an explicit GIT_DIR, so a later fetch from inside a hook is safe. On a warm
# cache this costs tens of milliseconds per module.
#
# GIT_CONFIG* is kept. `git rev-parse --local-env-vars` lists it alongside the
# location variables, but it is how a caller hands git config to the fetch (a
# url.<base>.insteadOf rewrite for a private module, `git -c ...` on the
# commit), and clearing it breaks the download.
#
# Each module downloads in module mode (GOWORK=off): `go mod tidy` works on one
# module at a time, and a module left out of go.work cannot run in workspace
# mode at all.
#
# Usage: go-mod-download-worktree-safe.sh [--exclude <dir>]...
#   --exclude <dir>  skip the module at <dir> and every module below it, for a
#                    module that cannot download anywhere (e.g. its `replace`
#                    points at a sibling checkout that CI does not have)
set -euo pipefail

excludes=""
while [ $# -gt 0 ]; do
  case "$1" in
    --exclude)
      if [ $# -lt 2 ] || [ -z "$2" ]; then
        echo "ERROR: --exclude needs a directory" >&2
        exit 2
      fi
      dir=${2#./}
      excludes="$excludes${dir%/}
"
      shift 2
      ;;
    *)
      echo "ERROR: unexpected argument '$1' (this hook takes no filenames; see --exclude)" >&2
      exit 2
      ;;
  esac
done

is_excluded() {
  local x
  while IFS= read -r x; do
    [ -z "$x" ] && continue
    case "$1" in
      "$x" | "$x"/*) return 0 ;;
    esac
  done <<EOF
$excludes
EOF
  return 1
}

modules=$(find . -name go.mod -not -path './.git/*' -not -path '*/vendor/*' -not -path '*/node_modules/*' |
  sed -e 's|/go\.mod$||' -e 's|^\./||' | sort)
[ -z "$modules" ] && exit 0

# Captured before the loop rather than inlined into it: a failure inside a
# `for` word list is invisible to `set -e`, and an empty list would clear
# nothing while the hook reported success.
local_vars=$(git rev-parse --local-env-vars)
if [ -z "$local_vars" ]; then
  echo "ERROR: 'git rev-parse --local-env-vars' listed nothing; refusing to run go with GIT_DIR set" >&2
  exit 1
fi
for var in $local_vars; do
  case "$var" in
    GIT_CONFIG*) ;;
    *) unset "$var" ;;
  esac
done

status=0
while IFS= read -r mod; do
  if is_excluded "$mod"; then
    continue
  fi
  # stdin from /dev/null: this loop reads the module list from stdin, and a
  # credential prompt under `go` must not consume the rest of it.
  if ! out=$(cd "$mod" && GOWORK=off go mod download </dev/null 2>&1); then
    echo "ERROR: 'go mod download' failed in $mod"
    printf '%s\n' "$out" | sed 's/^/       /'
    status=1
  fi
done <<EOF
$modules
EOF

if [ "$status" -ne 0 ]; then
  echo "       This hook downloads modules with GIT_DIR cleared so that the Go hooks"
  echo "       after it never make a module's first git fetch from inside the commit"
  echo "       (that fetch re-initializes this repository as bare). Fix the download,"
  echo "       or --exclude a module that cannot download anywhere."
fi
exit $status
