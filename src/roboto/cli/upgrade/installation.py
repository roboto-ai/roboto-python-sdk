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
import json
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
"""Name of the step under which ``roboto upgrade`` reports what happened to the CLI."""

DOWNLOAD_TIMEOUT_SECONDS = 300
FIRST_RUN_TIMEOUT_SECONDS = 300
"""Number of seconds ``roboto upgrade`` waits for the downloaded binary to run ``--version``."""

HOMEBREW_INFO_TIMEOUT_SECONDS = 60

_RUN_AGAIN = "Run `roboto upgrade` again."


class InstallKind(enum.Enum):
    """Installation method of the running Roboto CLI, which decides how ``roboto upgrade`` upgrades it."""

    StandaloneBinary = "standalone_binary"
    """Replaceable release binary, such as the one ``install.sh`` or ``install.ps1`` puts in ``~/.local/bin``."""

    Homebrew = "homebrew"
    """``roboto-ai/tap/roboto`` Homebrew cask."""

    HomebrewLinkReplaced = "homebrew_link_replaced"
    """Release binary in place of the link the installed ``roboto-ai/tap/roboto`` cask puts on ``PATH``.

    Homebrew cannot upgrade the cask until that file is removed.
    """

    DebianPackage = "debian_package"
    """``.deb`` package, which installs ``/usr/bin/roboto``."""

    PythonPackage = "python_package"
    """``roboto`` Python package, run as the ``roboto`` command it installs or as ``python -m roboto.cli``."""


@dataclasses.dataclass(frozen=True)
class Installation:
    """Installation of the running Roboto CLI, as ``detect_installation`` finds it."""

    kind: InstallKind
    """How the CLI was installed."""

    path: pathlib.Path
    """Executable to upgrade: the release binary, or the Python interpreter that runs the package.

    On macOS and Linux, the release binary's path has symbolic links resolved.
    """


def detect_installation(
    env: collections.abc.Mapping[str, str], executable: str, frozen: bool, platform: str
) -> Installation:
    """Return how the running Roboto CLI was installed and the executable to upgrade.

    Args:
        env: Environment variables of the running process. The macOS and Linux release binaries set
            ``ROBOTO_RELEASE_BINARY`` to their own path when they start. On Linux that path has symbolic links
            resolved; on macOS it is the path the binary was started from, such as the link Homebrew puts on ``PATH``.
        executable: Path of the running interpreter or bundled executable, as ``sys.executable`` gives it.
        frozen: Whether the CLI runs from a bundled executable that sets ``sys.frozen``, as the Windows release
            binary does.
        platform: Platform the CLI runs on, as ``sys.platform`` names it.
    """
    # Only the release binary sets this variable, to its own path, so it never names another program to replace.
    release_binary = env.get("ROBOTO_RELEASE_BINARY")
    if release_binary:
        # Resolved for two reasons: a Homebrew install started through Homebrew's link is then recognized by its
        # Caskroom path, and upgrading through the CLI replaces the file a link points to, not the link.
        path = pathlib.Path(release_binary).resolve()
        if "Caskroom" in path.parts:
            return Installation(kind=InstallKind.Homebrew, path=path)

        # Homebrew's bin and Caskroom directories sit side by side under its prefix. A resolved path in that bin, with
        # the cask installed, is a file in place of the cask's link.
        if path.parent.name == "bin" and (path.parent.parent / "Caskroom" / "roboto").is_dir():
            return Installation(kind=InstallKind.HomebrewLinkReplaced, path=path)
        if platform.startswith("linux") and path == pathlib.Path("/usr/bin/roboto"):
            return Installation(kind=InstallKind.DebianPackage, path=path)
        return Installation(kind=InstallKind.StandaloneBinary, path=path)

    if frozen:
        return Installation(kind=InstallKind.StandaloneBinary, path=pathlib.Path(executable))

    # Not resolved: a venv's python is a link to the base interpreter, and pip must run from the venv's.
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
    2. It is checked against the release's SHA-256 checksum file, when the release publishes one. A checksum file
       with no entry for the binary, or with a different checksum, stops the upgrade.
    3. It is run once with ``--version``, to make sure it works and reports ``latest_version``. A binary that reports
       any other version, as one from an out-of-date mirror can, stops the upgrade.
    4. It is renamed over the installed file. On Windows, which does not replace a running executable but does rename
       one, the installed file is first renamed to ``.<name>.old`` beside it, and the next run of the CLI deletes it.

    A Homebrew install is upgraded with ``brew upgrade --cask``, which installs the newest version Homebrew has. That
    can be older than ``latest_version``, and the outcome reports the version Homebrew installed. A release binary in
    place of the cask's link gets the commands that remove it and reinstall the cask, even when it is already the
    latest version. A ``.deb`` package or a Python package gets the apt or pip command that upgrades it.

    Args:
        download_url: URL of the directory that holds the release's files, such as a mirror. ``None`` uses the GitHub
            release for ``latest_version``.

    Returns:
        Outcome of the ``Roboto CLI`` step. ``roboto.cli.outcome.StepStatus.ActionNeeded`` means the CLI cannot upgrade
        this install itself, and the next steps say what to do. A standalone binary is replaced only when the status is
        ``StepStatus.Done``, and nothing is downloaded or run unless ``roboto.cli.config.is_version_outdated`` finds
        ``current_version`` older than ``latest_version``.
    """
    # Checked before the version, because this file is often the latest version already: older releases' `roboto
    # upgrade` wrote it over the cask's link. Homebrew cannot upgrade the cask until the file is removed.
    if installation.kind is InstallKind.HomebrewLinkReplaced:
        # `brew reinstall`, not `brew upgrade`: when Homebrew already records the latest version, upgrade does nothing,
        # so removing the file would leave no `roboto` on PATH. The brew beside the file, not the one on PATH, because
        # on a Mac with both an Apple silicon and an Intel Homebrew, the other one does not have this cask.
        brew = installation.path.parent / "brew"
        return StepOutcome(
            step=CLI_STEP,
            status=StepStatus.ActionNeeded,
            summary=f"Homebrew can't upgrade this CLI: the `roboto` at {installation.path} wasn't installed by "
            + "Homebrew, and Homebrew won't replace it.",
            next_steps=(
                f"To fix it, run `rm {quote_for_shell(str(installation.path))} && "
                + f"{quote_for_shell(str(brew))} reinstall --cask {HOMEBREW_CASK}`.",
            ),
        )

    if not is_version_outdated(current_version, latest_version):
        return StepOutcome(
            step=CLI_STEP,
            status=StepStatus.AlreadyDone,
            summary=f"Up to date ({current_version}).",
        )

    if download_url is None:
        download_url = f"{RELEASES_URL}/download/v{latest_version}"
    # Accept a trailing slash, as install.sh and install.ps1 do for ROBOTO_DOWNLOAD_URL.
    download_url = download_url.removesuffix("/")

    if installation.kind is InstallKind.StandaloneBinary:
        return _replace_binary(installation.path, current_version, latest_version, download_url)

    if installation.kind is InstallKind.Homebrew:
        return _upgrade_with_homebrew(current_version, latest_version)

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


# Versions compare by PEP 440, so "1.1" and "1.1.0" are the same version. When either is not a valid PEP 440 version,
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
    # Every download error fails the upgrade:
    # - OSError: network and HTTP errors (urllib.error.URLError is one).
    # - ValueError: a download_url without a scheme.
    # - http.client.HTTPException: a download cut off partway (IncompleteRead), or a download_url whose port is not a
    #   number (InvalidURL).
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

    # The new binary is written in full beside the old one and then renamed into place, so an interrupted upgrade never
    # leaves a partly written `roboto`, and the one running now keeps working while it is replaced.
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
    """Delete the old copy of the CLI that ``roboto upgrade`` or ``install.ps1`` renamed on Windows, if it is there.

    The Windows release binary calls this each time it starts. Windows does not delete an executable while it runs,
    so the upgrade leaves the old copy for the next run of the CLI to delete. A copy that is still running, such as a
    ``roboto`` command started before the upgrade, stays until a later run.

    Args:
        executable: Path of the running CLI's executable.
    """
    # Any OSError, such as the one for a copy that is still running, leaves the file for a later run.
    with contextlib.suppress(OSError):
        _replaced_executable_path(executable).unlink(missing_ok=True)


def _replaced_executable_path(target: pathlib.Path) -> pathlib.Path:
    # install.ps1 gives the roboto.exe it replaces this same name.
    return target.with_name(f".{target.name}.old")


def _swap_in(staged: pathlib.Path, target: pathlib.Path) -> None:
    if sys.platform != "win32":
        os.replace(staged, target)
        return

    # Windows does not replace the running executable, so it moves aside first (see upgrade_installation).
    replaced = _replaced_executable_path(target)
    # An old copy left by an earlier upgrade or install. If it is still running, Windows refuses to delete it, and the
    # upgrade stops here, before anything has moved.
    try:
        replaced.unlink(missing_ok=True)
    except PermissionError as exc:
        raise _OldCopyNotDeletedError(str(exc)) from exc
    os.replace(target, replaced)
    try:
        os.replace(staged, target)
    except BaseException:
        # Put the installed file back on any failure, Ctrl-C included, so no CLI is left missing, then re-raise.
        try:
            os.replace(replaced, target)
        except OSError:
            raise _PreviousVersionNotRestoredError(replaced) from None
        raise


class _OldCopyNotDeletedError(OSError):
    """Windows refused to delete the copy of the CLI that an earlier upgrade or install renamed.

    Windows refuses while a command started from that copy is running. The message is the error Windows gave.
    """


class _PreviousVersionNotRestoredError(OSError):
    """The new executable could not be put in place, and the previous one, moved aside, could not be moved back.

    ``previous`` is the path the previous version was moved to.
    """

    def __init__(self, previous: pathlib.Path) -> None:
        super().__init__(f"the previous version couldn't be moved back from {previous}")
        self.previous = previous


def _upgrade_with_homebrew(current_version: str, latest_version: str) -> StepOutcome:
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
            # brew also exits 0 when its tap is behind GitHub's releases, as it is for a while after each release and
            # for any release the tap skips. It then installs the tap's newest version, or nothing. When brew cannot
            # report the installed version, the outcome does not claim an upgrade.
            installed = _homebrew_installed_version(brew)
            if installed is not None and _is_same_version(installed, latest_version):
                return StepOutcome(
                    step=CLI_STEP,
                    status=StepStatus.Done,
                    summary=f"Upgraded to {latest_version} with Homebrew.",
                )
            if installed is not None and is_version_outdated(current_version, installed):
                return StepOutcome(
                    step=CLI_STEP,
                    status=StepStatus.Done,
                    summary=f"Upgraded to {installed} with Homebrew. Version {latest_version} isn't in Homebrew yet.",
                )
            return StepOutcome(
                step=CLI_STEP,
                status=StepStatus.ActionNeeded,
                summary=f"Version {latest_version} is available, but Homebrew didn't report it as installed.",
                next_steps=("Run `roboto upgrade` again later.",),
            )
        reason = f"exit status {completed.returncode}"

    return StepOutcome(
        step=CLI_STEP,
        status=StepStatus.Failed,
        summary=f"Homebrew couldn't upgrade it ({reason}).",
        next_steps=(_RUN_AGAIN,),
    )


def _homebrew_installed_version(brew: str) -> typing.Optional[str]:
    # The cask version Homebrew records as installed, or None when brew cannot report one.
    try:
        completed = subprocess.run(  # noqa: S603
            [brew, "info", "--cask", "--json=v2", HOMEBREW_CASK],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=HOMEBREW_INFO_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        installed = json.loads(completed.stdout)["casks"][0]["installed"]
    except (ValueError, LookupError, TypeError):
        return None
    return installed if isinstance(installed, str) else None


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS, context=https_ssl_context()) as response:  # noqa: S310
        return response.read()


def _download_if_published(url: str) -> typing.Optional[bytes]:
    # None when the release does not publish the file. Any other error propagates.
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
