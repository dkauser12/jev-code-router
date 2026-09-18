#!/bin/sh
# Build dist/jev-<version>.tar.gz (+ .sha256) from the jev/ skill folder.
#
# Usage: sh .github/package.sh vX.Y.Z
#
# Prefers `git archive` on a clean checkout (what CI runs on); falls back to a
# plain, deterministic tar of the working tree otherwise. Output: a top-level
# `jev/` folder, sorted member order, fixed mtimes, no .DS_Store/AppleDouble/
# __pycache__.
set -eu

main() {
  version=${1:-}
  [ -n "$version" ] || { echo 'usage: package.sh vX.Y.Z' >&2; exit 1; }
  case "$version" in
    v[0-9]*.[0-9]*.[0-9]*) ;;
    *)
      echo "package.sh: invalid version '$version', expected vMAJOR.MINOR.PATCH" >&2
      exit 1
      ;;
  esac

  # Avoid AppleDouble (._*) sidecar files when copying/archiving on macOS.
  COPYFILE_DISABLE=1
  export COPYFILE_DISABLE

  root=$(cd -- "$(dirname -- "$0")/.." && pwd) || {
    echo 'package.sh: cannot resolve repository root' >&2
    exit 1
  }
  dist="$root/dist"
  archive="jev-$version.tar.gz"

  stage=""
  trap 'rm -rf "${stage:-}"' EXIT HUP INT TERM
  stage=$(mktemp -d) || { echo 'package.sh: mktemp failed' >&2; exit 1; }

  if command -v git >/dev/null 2>&1 \
     && git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
     && [ -z "$(git -C "$root" status --porcelain -- jev)" ]; then
    git -C "$root" archive --prefix=jev/ HEAD:jev | (cd "$stage" && tar -xf -)
  else
    mkdir -p "$stage/jev"
    (cd "$root/jev" && find . -type f \
        ! -name '.DS_Store' \
        ! -name '._*' \
        ! -path '*/__pycache__/*' \
        -print) | while IFS= read -r f; do
      rel=${f#./}
      mkdir -p "$stage/jev/$(dirname "$rel")"
      cp -p "$root/jev/$rel" "$stage/jev/$rel"
    done
  fi

  # Deterministic member metadata: every file gets the same fixed mtime.
  find "$stage" -exec touch -t 202601010000 {} +

  mkdir -p "$dist"
  rm -f "$dist/$archive" "$dist/$archive.sha256"

  files=$(cd "$stage" && find jev -type f | LC_ALL=C sort)
  [ -n "$files" ] || { echo 'package.sh: no files staged from jev/' >&2; exit 1; }
  # shellcheck disable=SC2086  # $files is a newline-separated list of tar members, splitting is intended
  (cd "$stage" && tar -czf "$dist/$archive" $files)

  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$dist" && sha256sum "$archive" > "$archive.sha256")
  elif command -v shasum >/dev/null 2>&1; then
    (cd "$dist" && shasum -a 256 "$archive" > "$archive.sha256")
  else
    echo 'package.sh: sha256sum or shasum is required' >&2
    exit 1
  fi

  printf 'Built %s/%s\n' "$dist" "$archive"
}

main "$@"
