#!/bin/sh
# Install the jev Agent Skill (CLI + specs) without Python packaging, Node or root.
#
# Usage:
#   curl --proto '=https' --tlsv1.2 -fLsS \
#     https://github.com/okooo5km/jev/releases/download/v0.3.1/install.sh -o /tmp/jev-install.sh
#   sh /tmp/jev-install.sh
#
# Env overrides: JEV_VERSION, JEV_HOME, JEV_INSTALL_DIR, JEV_ARCHIVE_DIR.
# Everything executable lives inside main(), called only on the last line, so a
# truncated download (e.g. a `curl | sh` cut off mid-transfer) fails to parse
# instead of running a partial script.
set -eu

main() {
  version=${JEV_VERSION:-v0.3.1}
  case "$version" in
    v[0-9]*.[0-9]*.[0-9]*) ;;
    *)
      echo "install.sh: invalid JEV_VERSION '$version', expected vMAJOR.MINOR.PATCH" >&2
      exit 1
      ;;
  esac

  # Target directory, resolved early so a bad JEV_HOME fails before any download.
  home=${JEV_HOME:-"${XDG_DATA_HOME:-$HOME/.local/share}/jev"}
  home=${home%/}
  if [ -L "$home" ]; then
    echo "install.sh: $home is a symlink; refusing to replace it. Remove it or set JEV_HOME." >&2
    exit 1
  fi

  command -v python3 >/dev/null 2>&1 || {
    echo 'install.sh: python3 (>= 3.9) is required to run jev' >&2
    exit 1
  }
  py_ok=$(python3 -c 'import sys; print(1 if sys.version_info[:2] >= (3, 9) else 0)')
  if [ "$py_ok" != 1 ]; then
    py_version=$(python3 -c 'import sys; print(sys.version.split()[0])')
    echo "install.sh: python3 >= 3.9 is required; found $py_version" >&2
    exit 1
  fi
  py_toml_ok=$(python3 -c 'import sys; print(1 if sys.version_info[:2] >= (3, 11) else 0)')
  if [ "$py_toml_ok" != 1 ]; then
    echo 'install.sh: note: python3 < 3.11 has no tomllib. Built-in specs are JSON and work fine; custom TOML specs need Python 3.11+ (or use JSON).' >&2
  fi

  archive="jev-$version.tar.gz"
  base="https://github.com/okooo5km/jev/releases/download/$version"

  work=""
  stage=""
  trap 'rm -rf "${stage:-}" "${work:-}"' EXIT HUP INT TERM
  work=$(mktemp -d) || { echo 'install.sh: mktemp failed' >&2; exit 1; }

  if [ -n "${JEV_ARCHIVE_DIR:-}" ]; then
    cp "$JEV_ARCHIVE_DIR/$archive" "$work/$archive"
    cp "$JEV_ARCHIVE_DIR/$archive.sha256" "$work/$archive.sha256"
  else
    command -v curl >/dev/null 2>&1 || {
      echo 'install.sh: curl is required (or set JEV_ARCHIVE_DIR for an offline install)' >&2
      exit 1
    }
    curl --proto '=https' --tlsv1.2 -fLsS "$base/$archive" -o "$work/$archive"
    curl --proto '=https' --tlsv1.2 -fLsS "$base/$archive.sha256" -o "$work/$archive.sha256"
  fi

  # Verify SHA-256 before anything is extracted or touched.
  expected=$(awk 'NR==1 {print $1}' "$work/$archive.sha256")
  if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$work/$archive" | awk '{print $1}')
  elif command -v shasum >/dev/null 2>&1; then
    actual=$(shasum -a 256 "$work/$archive" | awk '{print $1}')
  else
    echo 'install.sh: sha256sum or shasum is required' >&2
    exit 1
  fi
  if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
    echo 'install.sh: checksum mismatch; nothing installed.' >&2
    exit 1
  fi

  tar -xzf "$work/$archive" -C "$work"
  [ -f "$work/jev/scripts/jev" ] || {
    echo 'install.sh: archive does not contain jev/scripts/jev' >&2
    exit 1
  }
  chmod 755 "$work/jev/scripts/jev"

  # Stage the new install next to the target, then swap it in with two renames
  # so a failure before the swap never touches an existing install, and a
  # failure during the swap restores it immediately.
  parent=$(dirname -- "$home")
  mkdir -p "$parent"
  stage="$parent/.jev-install-$$"
  rm -rf "$stage"
  cp -R "$work/jev" "$stage"
  chmod 755 "$stage/scripts/jev"

  old=""
  if [ -e "$home" ] || [ -L "$home" ]; then
    old="$parent/.jev-old-$$"
    rm -rf "$old"
    mv -f -- "$home" "$old"
  fi
  if mv -f -- "$stage" "$home"; then
    stage=""
    if [ -n "$old" ]; then
      rm -rf "$old"
      old=""
    fi
  else
    echo 'install.sh: failed to activate the new install' >&2
    if [ -n "$old" ]; then
      mv -f -- "$old" "$home" 2>/dev/null || true
      echo 'install.sh: previous install restored' >&2
    fi
    exit 1
  fi

  bin=${JEV_INSTALL_DIR:-"$HOME/.local/bin"}
  mkdir -p "$bin"
  ln -sfn "$home/scripts/jev" "$bin/jev"

  "$bin/jev" --version
  printf 'Installed: %s (linked from %s/jev)\n' "$home" "$bin"

  case ":$PATH:" in
    *":$bin:"*) ;;
    *)
      printf 'Add the installation directory to PATH. For the default location run:\n'
      # shellcheck disable=SC2016  # $PATH here is literal text for the user to paste, not an expansion
      printf '  export PATH="%s:$PATH"\n' "$bin"
      printf 'Add that line to your shell profile to keep it in new terminals; this installer does not edit shell profiles.\n'
      ;;
  esac

  if [ -z "${TYPESAFE_API_KEY:-}" ] && [ -z "${OPENROUTER_API_KEY:-}" ]; then
    cfg_dir=${XDG_CONFIG_HOME:-"$HOME/.config"}/jev
    has_key=0
    if [ -f "$cfg_dir/.env" ] \
       && grep -Eq '^(export[ 	]+)?(TYPESAFE_API_KEY|OPENROUTER_API_KEY)=' "$cfg_dir/.env" 2>/dev/null; then
      has_key=1
    fi
    if [ "$has_key" -eq 0 ]; then
      printf '\nNext step: run "%s/jev" auth set in your own terminal to store a TypeSafe key (default)\n' "$bin"
      printf '(hidden input, never echoed; create a key first at https://console.typesafe.ai/settings/keys).\n'
      printf 'Or run "%s/jev" auth set --provider openrouter to use an OpenRouter key instead.\n' "$bin"
      printf 'CI and other non-interactive environments can set TYPESAFE_API_KEY or OPENROUTER_API_KEY instead.\n'
    fi
  fi
}

main "$@"
