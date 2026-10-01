# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import contextlib
import dataclasses
import enum
import hashlib
import http.client
import os
import pathlib
import platform as platform_module
import shutil
import subprocess
import sys
import tempfile
import typing
import urllib.error
import urllib.request

from packaging.version import InvalidVersion, Version

from ...http.tls import https_ssl_context
from ..config import is_version_outdated
from ..outcome import StepOutcome, StepStatus
from ..terminal import quote_for_shell

RELEASES_URL = "https://github.com/roboto-ai/roboto-python-sdk/releases"
CHECKSUMS_FILE = "roboto-sha256sums.txt"
HOMEBREW_CASK = "roboto-ai/tap/roboto"

CLI_STEP = "Roboto CLI"
"""The step name under which ``roboto upgrade`` reports what happened to the CLI."""

DOWNLOAD_TIMEOUT_SECONDS = 300
FIRST_RUN_TIMEOUT_SECONDS = 300

_RUN_AGAIN = "Run `roboto upgrade` again."


class InstallKind(enum.Enum):
    """How the running Roboto CLI was installed, which decides how it can be upgraded."""

    StandaloneBinary = "standalone_binary"
    """A release binary the user can replace, such as the one ``install.sh`` or ``install.ps1`` puts in
    ``~/.local/bin``."""

    Homebrew = "homebrew"
    """The ``roboto-ai/tap/roboto`` Homebrew cask."""

    DebianPackage = "debian_package"
    """The ``.deb`` package, which installs ``/usr/bin/roboto``."""

    PythonPackage = "python_package"
    """The ``roboto`` Python package, run as the ``roboto`` command it installs or as ``python -m roboto.cli``."""


@dataclasses.dataclass(frozen=True)
class Installation:
    kind: InstallKind
    path: pathlib.Path
    """The installed executable: the release binary, or the Python interpreter that runs the package."""


def detect_installation(
    env: collections.abc.Mapping[str, str], executable: str, frozen: bool, platform: str
) -> Installation:
    """Work out how the running Roboto CLI was installed.

    Args:
        env: The process's environment variables. The macOS and Linux release binaries set ``ROBOTO_RELEASE_BINARY``
            to their own path, with symbolic links resolved, when they start.
        executable: ``sys.executable``.
        frozen: Whether the CLI runs from a bundled executable (PyInstaller sets ``sys.frozen``), as the Windows
            release binary does.
        platform: ``sys.platform``.

    Returns:
        The kind of install and the executable to upgrade.
    """
    # Only the release binary sets this variable, to its own path, so it never names another program to replace.
    release_binary = env.get("ROBOTO_RELEASE_BINARY")
    if release_binary:
        path = pathlib.Path(release_binary)
        # Homebrew keeps each cask's files under a Caskroom directory, and the variable holds the resolved path, not
        # the symlink Homebrew puts on PATH.
        if "Caskroom" in path.parts:
            return Installation(kind=InstallKind.Homebrew, path=path)
        if platform.startswith("linux") and path == pathlib.Path("/usr/bin/roboto"):
            return Installation(kind=InstallKind.DebianPackage, path=path)
        return Installation(kind=InstallKind.StandaloneBinary, path=path)

    if frozen:
        return Installation(kind=InstallKind.StandaloneBinary, path=pathlib.Path(executable))

    return Installation(kind=InstallKind.PythonPackage, path=pathlib.Path(executable))


def upgrade_installation(
    installation: Installation,
    current_version: str,
    latest_version: str,
    download_url: typing.Optional[str] = None,
) -> StepOutcome:
    """Upgrade the Roboto CLI to ``latest_version`` the way it was installed.

    A standalone release binary is replaced in place:

    1. The release's binary for this platform is downloaded.
    2. It's checked against the release's SHA-256 checksum file, when the release publishes one. A checksum file with
       no entry for the binary, or with a different checksum, stops the upgrade.
    3. It's run once with ``--version``, to make sure it works and reports ``latest_version``. A binary that reports
       any other version, as one from an out-of-date mirror can, stops the upgrade.
    4. It's renamed over the installed file. On Windows, which won't replace a running executable but will rename one,
       the installed file is first renamed to ``.<name>.old`` beside it, and the next run of the CLI deletes it.

    A Homebrew install is upgraded with ``brew upgrade --cask``. A .deb package or a Python package gets the apt or
    pip command that upgrades it.

    Args:
        installation: How the CLI was installed, from :func:`detect_installation`.
        current_version: The running CLI's version.
        latest_version: The version to upgrade to.
        download_url: Where the release's files are, such as a mirror. Defaults to the GitHub release for
            ``latest_version``.

    Returns:
        What happened, as the ``Roboto CLI`` step. ``ActionNeeded`` means this kind of install can't be upgraded by
        the CLI itself, and the next steps say how. The installed CLI is unchanged unless the status is ``Done``, and
        nothing is downloaded or run unless :func:`~roboto.cli.config.is_version_outdated` finds ``current_version``
        older than ``latest_version``.
    """
    if not is_version_outdated(current_version, latest_version):
        return StepOutcome(
            step=CLI_STEP,
            status=StepStatus.AlreadyDone,
            summary=f"Up to date ({current_version}).",
        )

    if download_url is None:
        download_url = f"{RELEASES_URL}/download/v{latest_version}"
    # The installer accepts ROBOTO_DOWNLOAD_URL with a trailing slash too.
    download_url = download_url.removesuffix("/")

    if installation.kind is InstallKind.StandaloneBinary:
        return _replace_binary(installation.path, current_version, latest_version, download_url)

    if installation.kind is InstallKind.Homebrew:
        return _upgrade_with_homebrew(latest_version)

    if installation.kind is InstallKind.DebianPackage:
        deb = f"roboto-linux-{_machine()}_{latest_version}.deb"
        return StepOutcome(
            step=CLI_STEP,
            status=StepStatus.ActionNeeded,
            summary=f"Version {latest_version} is available.",
            next_steps=(f"To upgrade, run `curl -fLO {download_url}/{deb} && sudo apt install ./{deb}`.",),
        )

    return StepOutcome(
        step=CLI_STEP,
        status=StepStatus.ActionNeeded,
        summary=f"Version {latest_version} is available.",
        next_steps=(
            f"To upgrade, run `{quote_for_shell(str(installation.path))} -m pip install --upgrade roboto`.",
            # An environment that uv creates has no pip, so the command above fails there.
            "In an environment managed by another tool, such as uv or Poetry, upgrade roboto with that tool.",
        ),
    )


# Versions compare by PEP 440, so "1.1" and "1.1.0" are the same version. When either isn't a valid PEP 440 version,
# only identical strings are the same version.
def _is_same_version(reported: str, expected: str) -> bool:
    try:
        return Version(reported) == Version(expected)
    except InvalidVersion:
        return reported == expected


def _replace_binary(target: pathlib.Path, current_version: str, latest_version: str, download_url: str) -> StepOutcome:
    asset = _release_asset()

    def failed(summary: str, *next_steps: str) -> StepOutcome:
        return StepOutcome(step=CLI_STEP, status=StepStatus.Failed, summary=summary, next_steps=next_steps)

    print(f"  Downloading {download_url}/{asset}")
    try:
        binary = _download(f"{download_url}/{asset}")
        checksums = _download_if_published(f"{download_url}/{CHECKSUMS_FILE}")
    # Every download error fails the upgrade: OSError for network and HTTP errors (urllib.error.URLError is one),
    # ValueError for a download_url without a scheme, and http.client.HTTPException for a download cut off partway
    # (IncompleteRead) or a download_url with a port that isn't a number (InvalidURL).
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return failed(f"The download failed: {exc}", "Check your network connection, then run `roboto upgrade` again.")

    if checksums is None:
        print(f"  Warning: this release publishes no {CHECKSUMS_FILE}, so the download can't be verified.")
    else:
        expected = _checksum_for(checksums.decode("utf-8", errors="replace"), asset)
        if expected is None:
            # Downloading again would find the same checksum file, so there is no next step to give.
            return failed(f"Couldn't verify the download: {CHECKSUMS_FILE} has no entry for {asset}.")
        if hashlib.sha256(binary).hexdigest() != expected:
            return failed(f"The download doesn't match its checksum in {CHECKSUMS_FILE}.", _RUN_AGAIN)

    # The new binary is written in full next to the old one before it's renamed into place, so an interrupted upgrade
    # never leaves a partly written `roboto`, and the one running now keeps working while it's replaced.
    try:
        fd, staged_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    except OSError as exc:
        # For example, a binary copied into a directory only an administrator can write to.
        return failed(
            f"Couldn't save the download: {exc}",
            f"Make sure you can write to {target.parent}, then run `roboto upgrade` again.",
        )
    staged = pathlib.Path(staged_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(binary)
            f.flush()
            os.fsync(f.fileno())
        staged.chmod(0o755)

        # Its first run also downloads the Python runtime it uses, so running it now spares the user that wait later.
        print("  Checking that the download runs")
        try:
            check = subprocess.run(  # noqa: S603
                [str(staged), "--version", "--suppress-upgrade-check"],
                capture_output=True,
                # This process's SCIE variables describe the binary running now, and the new one sets its own. A
                # release binary refuses to run when SCIE names neither one of its commands nor a file that exists.
                env={name: value for name, value in os.environ.items() if not name.startswith("SCIE")},
                stdin=subprocess.DEVNULL,
                encoding="utf-8",
                errors="replace",
                timeout=FIRST_RUN_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return failed(f"The download didn't run: {exc}", _RUN_AGAIN)
        if check.returncode != 0:
            return failed(f"The download didn't run (exit status {check.returncode}).", _RUN_AGAIN)
        reported_version = check.stdout.strip()
        if not _is_same_version(reported_version, latest_version):
            # Downloading again would fetch the same release, so there is no next step to give.
            what_it_is = f"version {reported_version}" if reported_version else "an unknown version"
            return failed(f"The download is {what_it_is}, not {latest_version}.")

        _swap_in(staged, target)
    except _OldCopyNotDeletedError as exc:
        return failed(
            f"Couldn't delete an old copy of the CLI: {exc}",
            "Close any other running `roboto` command, then run `roboto upgrade` again.",
        )
    except _PreviousVersionNotRestoredError as exc:
        return failed(
            "Couldn't upgrade, and couldn't move the previous version back.",
            f"Rename {exc.previous} to {target.name}, then run `roboto upgrade` again.",
        )
    except OSError as exc:
        return failed(f"Couldn't replace the installed version: {exc}", _RUN_AGAIN)
    finally:
        staged.unlink(missing_ok=True)

    return StepOutcome(
        step=CLI_STEP,
        status=StepStatus.Done,
        summary=f"Upgraded from {current_version} to {latest_version}.",
    )


def remove_replaced_executable(executable: pathlib.Path) -> None:
    """Delete the old copy of the CLI that ``roboto upgrade`` or ``install.ps1`` renamed on Windows, if it's there.

    Windows won't delete an executable while it runs, so the upgrade leaves the old copy for the next run of the CLI
    to delete. A copy that's still running, such as a ``roboto`` command started before the upgrade, stays until a
    later run.

    Args:
        executable: The path of the running CLI's executable.
    """
    # Any OSError, such as the one for a copy that's still running, leaves the file for a later run.
    with contextlib.suppress(OSError):
        _replaced_executable_path(executable).unlink(missing_ok=True)


def _replaced_executable_path(target: pathlib.Path) -> pathlib.Path:
    # install.ps1 gives the roboto.exe it replaces the same name.
    return target.with_name(f".{target.name}.old")


def _swap_in(staged: pathlib.Path, target: pathlib.Path) -> None:
    if sys.platform != "win32":
        os.replace(staged, target)
        return

    # Windows won't replace the running executable, so it moves aside first (see upgrade_installation).
    replaced = _replaced_executable_path(target)
    # An old copy left by an earlier upgrade or install. If it's still running, Windows won't delete it, and the upgrade
    # stops here, before anything has moved.
    try:
        replaced.unlink(missing_ok=True)
    except PermissionError as exc:
        raise _OldCopyNotDeletedError(str(exc)) from exc
    os.replace(target, replaced)
    try:
        os.replace(staged, target)
    except BaseException:
        # Put the installed file back on any failure, Ctrl-C included, so no CLI is left missing.
        try:
            os.replace(replaced, target)
        except OSError:
            raise _PreviousVersionNotRestoredError(replaced) from None
        raise


class _OldCopyNotDeletedError(OSError):
    """Windows refused to delete the copy of the CLI that an earlier upgrade or install renamed, as it does while a
    command started from that copy is running. The message is the error Windows gave."""


class _PreviousVersionNotRestoredError(OSError):
    """The new executable couldn't be put in place, and the previous one, moved aside, couldn't be moved back."""

    def __init__(self, previous: pathlib.Path) -> None:
        super().__init__(f"the previous version couldn't be moved back from {previous}")
        self.previous = previous


def _upgrade_with_homebrew(latest_version: str) -> StepOutcome:
    brew = shutil.which("brew")
    if brew is None:
        return StepOutcome(
            step=CLI_STEP,
            status=StepStatus.ActionNeeded,
            summary=f"Version {latest_version} is available. Homebrew installed this CLI, but `brew` isn't on your "
            + "PATH.",
            next_steps=("Add `brew` to your PATH, then run `roboto upgrade` again.",),
        )

    print(f"  Running `brew upgrade --cask {HOMEBREW_CASK}`")
    # brew's own progress goes straight to the terminal.
    try:
        completed = subprocess.run([brew, "upgrade", "--cask", HOMEBREW_CASK])  # noqa: S603
    except OSError as exc:
        reason = str(exc)
    else:
        if completed.returncode == 0:
            return StepOutcome(
                step=CLI_STEP,
                status=StepStatus.Done,
                summary=f"Upgraded to {latest_version} with Homebrew.",
            )
        reason = f"exit status {completed.returncode}"

    return StepOutcome(
        step=CLI_STEP,
        status=StepStatus.Failed,
        summary=f"Homebrew couldn't upgrade it ({reason}).",
        next_steps=(_RUN_AGAIN,),
    )


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS, context=https_ssl_context()) as response:  # noqa: S310
        return response.read()


def _download_if_published(url: str) -> typing.Optional[bytes]:
    # None when the release doesn't publish the file. Any other error propagates.
    try:
        return _download(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    except urllib.error.URLError as exc:
        # A file:// mirror that lacks the file raises this, where GitHub answers 404.
        if isinstance(exc.reason, FileNotFoundError):
            return None
        raise


def _checksum_for(checksums: str, asset: str) -> typing.Optional[str]:
    # Each line is `<sha256>  <file name>`, as `sha256sum` writes it, with `*` before the name in binary mode.
    for line in checksums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == asset:
            return parts[0].lower()
    return None


def _release_asset() -> str:
    if sys.platform == "win32":
        # The only Windows build. Windows on Arm runs it through emulation.
        return "roboto-windows-x86_64.exe"
    return f"roboto-{_operating_system()}-{_machine()}"


def _operating_system() -> str:
    return "macos" if sys.platform == "darwin" else "linux"


def _machine() -> str:
    machine = platform_module.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "aarch64"
    # An x86_64 binary on an Apple silicon Mac runs under Rosetta; upgrade it to the native build.
    if sys.platform == "darwin" and _runs_under_rosetta():
        return "aarch64"
    return "x86_64"


def _runs_under_rosetta() -> bool:
    try:
        result = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "sysctl.proc_translated"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.stdout.strip() == "1"
