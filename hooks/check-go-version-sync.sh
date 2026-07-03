#!/usr/bin/env bash
# Fail when a go.mod's `go` directive and the governing .tool-versions'
# golang pin drift apart — they must match so local (asdf) and CI build the
# same toolchain. For each go.mod (vendor/ and node_modules/ skipped), the
# governing pin is the nearest ancestor .tool-versions carrying a `golang`
# line; a module with no governing pin is skipped.
set -euo pipefail

status=0
while IFS= read -r modfile; do
  gomod_ver=$(awk '/^go [0-9]/{print $2; exit}' "$modfile")
  [ -z "$gomod_ver" ] && continue
  dir=$(dirname "$modfile")
  pin=""
  pinfile=""
  while :; do
    if [ -f "$dir/.tool-versions" ]; then
      v=$(awk '/^golang /{print $2; exit}' "$dir/.tool-versions")
      if [ -n "$v" ]; then pin="$v"; pinfile="$dir/.tool-versions"; break; fi
    fi
    [ "$dir" = "." ] && break
    dir=$(dirname "$dir")
  done
  [ -z "$pin" ] && continue
  if [ "$gomod_ver" != "$pin" ]; then
    echo "ERROR: $modfile has 'go $gomod_ver' but $pinfile pins 'golang $pin'"
    echo "       Keep them in lockstep (edit both in the same commit)."
    status=1
  fi
done < <(find . -name go.mod -not -path './.git/*' -not -path '*/vendor/*' -not -path '*/node_modules/*' | sed 's|^\./||')
exit $status
