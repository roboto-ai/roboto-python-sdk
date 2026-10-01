#!/usr/bin/env bash
# Install the Roboto CLI on macOS or Linux, then run `roboto setup` to finish setting up this machine.
#
#   curl -fsSL https://raw.githubusercontent.com/roboto-ai/roboto-python-sdk/main/install.sh | bash
#
# Options after `bash -s --` go to `roboto setup`, e.g. `... | bash -s -- --skip-mcp`.
#
# Environment variables:
#
#   ROBOTO_VERSION                Release to install, e.g. 0.58.0. Defaults to the latest release. A release from
#                                 before `roboto setup` existed is installed without running it.
#   ROBOTO_INSTALL_DIR            Directory to install the `roboto` command into. Defaults to ~/.local/bin.
#   ROBOTO_NO_MODIFY_PATH=1       Don't add the install directory to your shell's startup files.
#   ROBOTO_SKIP_SETUP=1           Don't run `roboto setup`.
#   ROBOTO_DOWNLOAD_URL           Download the release's files from this URL instead of GitHub, e.g. a mirror.
#                                 ROBOTO_VERSION is ignored when this is set.
#
# A `roboto` on your PATH that Homebrew installed is upgraded with `brew upgrade`, which ignores ROBOTO_VERSION and
# ROBOTO_DOWNLOAD_URL. To install the release binary alongside it, set ROBOTO_INSTALL_DIR.
#
# Until `main` on the last line, the script only defines settings and functions, so a download cut off partway
# through changes nothing.

set -euo pipefail

RELEASES_URL="https://github.com/roboto-ai/roboto-python-sdk/releases"
CHECKSUMS_FILE="roboto-sha256sums.txt"
PATH_LINE_COMMENT="# Added by the Roboto installer"

# -- Output ------------------------------------------------------------

say() {
  echo "==> $*"
}

detail() {
  echo "    $*"
}

warn() {
  echo "warning: $*" >&2
}

die() {
  echo "error: $*" >&2
  exit 1
}

# -- Platform ----------------------------------------------------------

detect_os() {
  case "$(uname -s)" in
    Linux) echo "linux" ;;
    Darwin) echo "macos" ;;
    MINGW* | MSYS* | CYGWIN*)
      die "this installer is for macOS and Linux. On Windows, run \`powershell -ExecutionPolicy ByPass -c \"irm https://raw.githubusercontent.com/roboto-ai/roboto-python-sdk/main/install.ps1 | iex\"\`."
      ;;
    *) die "unsupported operating system: $(uname -s). The Roboto CLI runs on macOS, Linux, and Windows." ;;
  esac
}

detect_arch() {
  local os="$1"
  local arch
  case "$(uname -m)" in
    x86_64 | amd64) arch="x86_64" ;;
    aarch64 | arm64) arch="aarch64" ;;
    *) die "unsupported processor: $(uname -m). The Roboto CLI runs on x86_64 and arm64 (aarch64)." ;;
  esac

  # A shell running under Rosetta reports x86_64 on an Apple Silicon Mac; the native build is faster.
  if [[ "$os" == "macos" && "$arch" == "x86_64" ]] && [[ "$(sysctl -n sysctl.proc_translated 2>/dev/null || true)" == "1" ]]; then
    arch="aarch64"
  fi

  echo "$arch"
}

require_glibc() {
  # musl's `ldd --version` exits with status 1, so its output is kept whatever the exit status.
  local ldd_version
  ldd_version="$(ldd --version 2>&1 || true)"
  if [[ "$ldd_version" == *musl* ]]; then
    die "this system uses musl, and the Roboto CLI binary needs glibc. To install the CLI with pip, run \`pip install roboto\`."
  fi
}

# -- Downloads ---------------------------------------------------------

# Downloads `url` to `destination`. Returns 0 on success; 2 when the file isn't there, because the server answered 404
# or a file:// URL names no file; and 1 for any other failure, after saying why on standard error.
download() {
  local url="$1"
  local destination="$2"
  local status=0 http_status=""

  if command -v curl >/dev/null 2>&1; then
    local options=(--fail --silent --show-error --location --write-out '%{http_code}' --output "$destination")
    # With --proto, curl also refuses a redirect from https to http. wget has no such option, so curl comes first.
    if [[ "$url" == https://* ]]; then
      options+=(--proto '=https' --tlsv1.2 --retry 3)
    fi
    http_status="$(curl "${options[@]}" "$url")" || status=$?
    # curl exits with status 37 when a file:// URL names a file it can't open.
    if [[ "$status" == 37 ]]; then
      return 2
    fi
  elif command -v wget >/dev/null 2>&1; then
    # --server-response prints the status line of each response, redirects included, even with --quiet. The last
    # one is the final answer.
    local responses
    responses="$(LC_ALL=C wget --quiet --server-response --output-document="$destination" "$url" 2>&1)" || status=$?
    http_status="$(awk '$1 ~ /^HTTP\// { code = $2 } END { print code }' <<<"$responses")"
    if [[ "$status" != 0 && "$http_status" != 404 ]]; then
      echo "wget exited with status $status${http_status:+ (HTTP status $http_status)}" >&2
    fi
  else
    die "the installer needs curl or wget to download the Roboto CLI."
  fi

  if [[ "$status" == 0 ]]; then
    return 0
  elif [[ "$http_status" == 404 ]]; then
    return 2
  fi
  return 1
}

release_base_url() {
  if [[ -n "${ROBOTO_DOWNLOAD_URL:-}" ]]; then
    echo "${ROBOTO_DOWNLOAD_URL%/}"
  elif [[ -n "${ROBOTO_VERSION:-}" ]]; then
    echo "$RELEASES_URL/download/v${ROBOTO_VERSION#v}"
  else
    echo "$RELEASES_URL/latest/download"
  fi
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d ' ' -f 1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d ' ' -f 1
  else
    die "the installer needs sha256sum or shasum to verify the download."
  fi
}

# Releases published before the checksum file existed can't be verified, so when the release has no checksum file,
# the installer warns and goes on. Any other failure to download it, a checksum file with no entry for the download,
# or a different checksum stops the install.
verify_download() {
  local base_url="$1"
  local asset="$2"
  local file="$3"
  local checksums="$4"

  local status=0 error
  error="$(download "$base_url/$CHECKSUMS_FILE" "$checksums" 2>&1)" || status=$?
  if [[ "$status" == 2 ]]; then
    warn "this release publishes no $CHECKSUMS_FILE, so the download can't be verified."
    return 0
  elif [[ "$status" != 0 ]]; then
    die "couldn't download $base_url/$CHECKSUMS_FILE (${error:-no reason given})."
  fi

  local expected
  expected="$(awk -v name="$asset" '$2 == name || $2 == "*" name { print tolower($1) }' "$checksums")"
  if [[ -z "$expected" ]]; then
    die "$CHECKSUMS_FILE has no entry for $asset."
  fi

  local actual
  actual="$(sha256_of "$file")"
  if [[ "$actual" != "$expected" ]]; then
    die "the downloaded $asset doesn't match its checksum in $CHECKSUMS_FILE (expected $expected, got $actual)."
  fi
  detail "Verified the download's SHA-256 checksum."
}

# -- Install -----------------------------------------------------------

# True when `existing` is the `roboto` that Homebrew installed from roboto-ai/tap. Being under Homebrew's prefix
# isn't enough on its own: on Intel Macs that prefix is /usr/local, where users also put downloaded binaries.
is_homebrew_install() {
  local existing="$1"
  command -v brew >/dev/null 2>&1 || return 1
  local prefix
  prefix="$(brew --prefix 2>/dev/null)" || return 1
  [[ "$(cd "$(dirname "$existing")" && pwd -P)/" == "$prefix"/* ]] || return 1
  brew list --cask roboto-ai/tap/roboto >/dev/null 2>&1
}

install_binary() {
  local install_dir="$1"
  local os="$2"
  local arch="$3"
  local work_dir="$4"

  local asset="roboto-${os}-${arch}"
  local base_url
  base_url="$(release_base_url)"

  say "Downloading $asset"
  download "$base_url/$asset" "$work_dir/$asset" || die "couldn't download $base_url/$asset."
  verify_download "$base_url" "$asset" "$work_dir/$asset" "$work_dir/$CHECKSUMS_FILE"

  mkdir -p "$install_dir"
  # Staged in the install directory and renamed into place, so an interrupted install never leaves a partly
  # written `roboto` behind, and a running `roboto` keeps working while it's replaced.
  local staged="$install_dir/.roboto.$$.tmp"
  # Replaces main's trap, which removes only the download directory, so Ctrl-C during the copy leaves nothing behind.
  # shellcheck disable=SC2064 # expand the paths now; they're local and gone by the time the trap runs
  trap "rm -rf $(printf '%q ' "$work_dir" "$staged")" EXIT
  cp "$work_dir/$asset" "$staged"
  chmod 755 "$staged"
  # Run before it replaces anything, so a download that doesn't run leaves an existing `roboto` in place.
  prepare_cli "$staged" || die "the downloaded $asset doesn't run."
  mv -f "$staged" "$install_dir/roboto"
  detail "Installed $install_dir/roboto"
}

prepare_cli() {
  local roboto="$1"
  say "Checking that the Roboto CLI runs (the first run downloads its Python runtime)"
  "$roboto" --version --suppress-upgrade-check >/dev/null
}

# -- PATH --------------------------------------------------------------

shell_startup_files() {
  case "$(basename "${SHELL:-}")" in
    zsh) echo "${ZDOTDIR:-$HOME}/.zshrc" ;;
    bash)
      echo "$HOME/.bashrc"
      # Login shells, such as a macOS Terminal window or an ssh session, read the first of .bash_profile,
      # .bash_login, and .profile that exists, and read .bashrc only if that file sources it. The line also goes
      # into that file. A new .bash_profile is created only when none of the three exists, since it would stop login
      # shells from reading .bash_login or .profile.
      local login_file
      for login_file in "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
        if [[ -f "$login_file" ]]; then
          echo "$login_file"
          return 0
        fi
      done
      echo "$HOME/.bash_profile"
      ;;
    fish) echo "${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/roboto.fish" ;;
    *) echo "$HOME/.profile" ;;
  esac
}

add_to_path() {
  local install_dir="$1"

  case ":$PATH:" in
    *":$install_dir:"*) return 0 ;;
  esac

  if [[ "${ROBOTO_NO_MODIFY_PATH:-}" == "1" ]]; then
    warn "$install_dir isn't on your PATH. Add it to run \`roboto\` from a new terminal."
    return 0
  fi

  local file line
  while IFS= read -r file; do
    if [[ "$file" == *.fish ]]; then
      line="fish_add_path \"$(escape_for_fish_double_quotes "$install_dir")\""
    else
      line="export PATH=\"$(escape_for_double_quotes "$install_dir"):\$PATH\""
    fi
    mkdir -p "$(dirname "$file")"
    if [[ -f "$file" ]] && grep -qF "$line" "$file"; then
      continue
    fi
    printf '\n%s\n%s\n' "$PATH_LINE_COMMENT" "$line" >>"$file"
    detail "Added $install_dir to PATH in $file"
  done < <(shell_startup_files)

  PATH_CHANGED=1
}

# Puts a backslash before each `$`, backtick, `"`, and `\`, so that sh, bash, and zsh read the result inside double
# quotes as the name it was given. Unescaped, `$` and a backtick would expand a variable or run a command from the name,
# `"` would end the quotes early, and `\` would change the character after it.
escape_for_double_quotes() {
  printf '%s' "$1" | sed 's/[\\$`"]/\\&/g'
}

# The same for fish, which leaves the backtick out: fish reads a backtick in double quotes as it is, and would keep a
# backslash put before one.
escape_for_fish_double_quotes() {
  printf '%s' "$1" | sed 's/[\\$"]/\\&/g'
}

# Warns when another `roboto` comes earlier on PATH than the installed one. Only checked when the install directory
# is already on PATH; otherwise add_to_path puts it first in new shells, or warns that it's missing.
warn_if_shadowed() {
  local installed="$1"
  case ":$PATH:" in
    *":$(dirname "$installed"):"*) ;;
    *) return 0 ;;
  esac
  local found
  found="$(command -v roboto || true)"
  if [[ -n "$found" && "$found" != "$installed" ]]; then
    warn "another \`roboto\` at $found comes first on your PATH, so typing \`roboto\` runs that one. Remove it or put $(dirname "$installed") earlier on your PATH."
  fi
}

# -- Main --------------------------------------------------------------

run_setup() {
  local roboto="$1"
  shift

  if [[ "${ROBOTO_SKIP_SETUP:-}" == "1" ]]; then
    return 0
  fi

  # Releases from before `roboto setup` existed refuse the command.
  if ! "$roboto" setup --help >/dev/null 2>&1; then
    say "Skipping \`roboto setup\`, which this release doesn't have"
    return 0
  fi

  # Piped into bash, this script's standard input is the script itself, so `roboto setup` reads the keyboard
  # through /dev/tty. Without a terminal, setup runs without asking anything.
  if [[ -t 1 ]] && (exec </dev/tty) 2>/dev/null; then
    "$roboto" setup "$@" </dev/tty
  else
    "$roboto" setup --no-input "$@"
  fi
}

main() {
  # Under sudo, the CLI and everything `roboto setup` writes would be owned by root, whether sudo points HOME at
  # root's home directory or leaves it at the user's. Running as root without sudo, as in a container, is allowed.
  if [[ -n "${SUDO_USER:-}" && "$EUID" == "0" ]]; then
    die "don't run the installer with sudo. To install the CLI for every user, download the file for your system (e.g. roboto-linux-x86_64) from $RELEASES_URL/latest to /usr/local/bin/roboto and make it executable."
  fi

  local os arch
  os="$(detect_os)"
  arch="$(detect_arch "$os")"
  if [[ "$os" == "linux" ]]; then
    require_glibc
  fi

  local install_dir="${ROBOTO_INSTALL_DIR:-$HOME/.local/bin}"
  # PATH needs full paths, so a relative directory is resolved against the one the installer runs in.
  if [[ "$install_dir" != /* ]]; then
    install_dir="$PWD/$install_dir"
  fi
  local existing roboto
  existing="$(command -v roboto || true)"
  PATH_CHANGED=0

  if [[ -z "${ROBOTO_INSTALL_DIR:-}" && -n "$existing" ]] && is_homebrew_install "$existing"; then
    say "Upgrading the Roboto CLI with Homebrew"
    brew upgrade --cask roboto-ai/tap/roboto || die "Homebrew couldn't upgrade the Roboto CLI."
    roboto="$existing"
    prepare_cli "$roboto" || die "the Roboto CLI Homebrew installed at $roboto doesn't run."
  else
    local work_dir
    work_dir="$(mktemp -d)"
    # shellcheck disable=SC2064 # expand work_dir now; it's local and gone by the time the trap runs
    trap "rm -rf $(printf '%q' "$work_dir")" EXIT
    install_binary "$install_dir" "$os" "$arch" "$work_dir"
    roboto="$install_dir/roboto"
    warn_if_shadowed "$roboto"
    add_to_path "$install_dir"
    export PATH="$install_dir:$PATH"
  fi

  local status=0
  run_setup "$roboto" "$@" || status=$?

  if [[ "$PATH_CHANGED" == "1" ]]; then
    echo
    echo "Open a new terminal (or run \`export PATH=\"$(escape_for_double_quotes "$install_dir"):\$PATH\"\`) to use the \`roboto\` command."
  fi
  exit "$status"
}

main "$@"
