#!/usr/bin/env bash
# Enforce ONE Go toolchain pin per repo, at the repo root, that every module
# respects. Three checks, in order:
#
#   1. no `golang` pin outside the repo root
#   2. a repo containing any go.mod has a root pin
#   3. every go.mod's `go` directive equals that root pin
#
# Why root-only rather than nearest-ancestor. This hook used to resolve each
# go.mod against the nearest ancestor .tool-versions carrying a `golang` line,
# and skip a module that had none. Both halves let drift in silently:
#
#   - a pin one directory down governs only its own subtree, so sibling modules
#     were skipped entirely and nothing checked them. In trader-tools the only
#     pin sat in apps/backend-go/, which is not an ancestor of apps/scribe/ or
#     chaos/ — so 2 of 3 modules were unguarded while the hook reported success.
#   - per-module pins go stale independently. They are separate files that must
#     be edited together, with nothing requiring it; one pin per repo cannot
#     disagree with itself.
#
# So the pin is a repo-level fact, and a nested one is now an error rather than
# a narrower scope. There is deliberately no opt-out: a repo that wants a module
# on a different toolchain wants a different repo, and the escape hatch is what
# would let the stale-pin case back in.
set -euo pipefail

status=0

# ── 1. a `golang` pin may exist only at the repo root ──────────────────────
#
# Checked FIRST and reported in full, because a nested pin is what makes the
# later checks read confusingly: the root pin and a module's go.mod can agree
# while the module's own asdf shell resolves the nested one instead.
while IFS= read -r tv; do
  [ "$tv" = ".tool-versions" ] && continue
  v=$(awk '/^golang /{print $2; exit}' "$tv")
  [ -z "$v" ] && continue
  echo "ERROR: $tv pins 'golang $v' outside the repo root"
  echo "       The Go pin is one per repo, in ./.tool-versions, and every module"
  echo "       must match it. Move this pin to the root (reconciling the values if"
  echo "       they differ) and delete the nested line."
  status=1
done < <(find . -name .tool-versions -not -path './.git/*' -not -path '*/vendor/*' -not -path '*/node_modules/*' | sed 's|^\./||')

# ── 2 & 3. the root pin exists, and every module matches it ────────────────
modules=$(find . -name go.mod -not -path './.git/*' -not -path '*/vendor/*' -not -path '*/node_modules/*' | sed 's|^\./||')
[ -z "$modules" ] && exit $status

root_pin=""
[ -f .tool-versions ] && root_pin=$(awk '/^golang /{print $2; exit}' .tool-versions)

if [ -z "$root_pin" ]; then
  echo "ERROR: this repo has a go.mod but no 'golang' pin in ./.tool-versions"
  echo "       Add one matching the modules' 'go' directive, so local asdf and CI"
  echo "       build the same toolchain. Modules found:"
  # shellcheck disable=SC2001
  echo "$modules" | sed 's|^|         |'
  exit 1
fi

while IFS= read -r modfile; do
  gomod_ver=$(awk '/^go [0-9]/{print $2; exit}' "$modfile")
  [ -z "$gomod_ver" ] && continue
  if [ "$gomod_ver" != "$root_pin" ]; then
    echo "ERROR: $modfile has 'go $gomod_ver' but ./.tool-versions pins 'golang $root_pin'"
    echo "       Keep every module and the root pin in lockstep (edit them in the"
    echo "       same commit)."
    status=1
  fi
done <<EOF
$modules
EOF

exit $status
