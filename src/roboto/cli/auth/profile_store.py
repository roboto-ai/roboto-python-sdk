# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import contextlib
import dataclasses
import datetime
import json
import os
import pathlib
import re
import tempfile
import typing

import filelock
import pydantic

from ...config import (
    DEFAULT_ROBOTO_PROFILE_NAME,
    RobotoConfigFileV1,
)

_PROFILE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_.\-]{1,100}")
_LOCK_TIMEOUT_SECONDS = 10.0


class ConfigFileError(Exception):
    """The config file cannot be safely read or updated. The file is left untouched."""


class ProfileAlreadyExistsError(ConfigFileError):
    """The target profile exists and the caller did not ask to overwrite it."""

    def __init__(self, config_file: pathlib.Path, profile_name: str, existing_profiles: list[str]) -> None:
        super().__init__(
            f"Profile '{profile_name}' already exists in '{config_file}'. "
            + f"Existing profiles: {', '.join(existing_profiles)}. "
            + "Choose another name with --profile, or pass --overwrite to replace its credentials."
        )
        self.profile_name = profile_name
        self.existing_profiles = existing_profiles


@dataclasses.dataclass(frozen=True)
class ProfileWriteResult:
    """Outcome of a successful :py:func:`write_profile` call."""

    config_file: pathlib.Path
    """Config file the profile was written to."""

    created_file: bool
    """The config file did not exist before this write."""

    is_default: bool
    """The written profile is the one used when no profile is selected."""

    v0_backup: typing.Optional[pathlib.Path] = None
    """Copy of the original file, when a legacy (V0) file was converted to the V1 format."""


def ensure_profile_writable(config_file: pathlib.Path, profile_name: str, overwrite: bool) -> None:
    """Raise early, without changing anything, for most of the reasons :py:func:`write_profile` would refuse a profile.

    Lets a caller fail before doing work whose result it would then have nowhere to store. Checks the profile name,
    the file's format, and whether the profile already exists. Does not check that the updated file would pass
    validation, and it takes no lock, so :py:func:`write_profile` can still refuse if the file changes in between.

    Args:
        config_file: Path of the config file. A missing file passes.
        profile_name: Profile the caller intends to write.
        overwrite: Whether the caller will pass ``overwrite=True`` to :py:func:`write_profile`.

    Raises:
        ProfileAlreadyExistsError: The profile exists and ``overwrite`` is false.
        ConfigFileError: The profile name is invalid or the file is not a config file this module can update.
    """
    _validate_profile_name(profile_name)
    document = _read_document(config_file)
    if document is not None:
        _raise_if_profile_exists(config_file, document.profiles, profile_name, overwrite)


def write_profile(
    config_file: pathlib.Path,
    profile_name: str,
    api_key: str,
    endpoint: str,
    overwrite: bool,
    set_default: bool = False,
) -> ProfileWriteResult:
    """Add or update one profile in a Roboto config file, preserving everything else in it.

    The file is edited as raw JSON, so profiles, profile settings and top-level keys this version of the SDK does not
    model survive the write. A legacy (V0) file is converted to the V1 format; a copy of the original is kept next to
    it. The write holds an exclusive lock and replaces the file atomically, so concurrent logins cannot lose each
    other's profiles and a crash cannot leave a half-written file. The result is readable only by its owner.

    Args:
        config_file: Path of the config file. Created, along with an owner-only parent directory, if missing.
        profile_name: Profile to write.
        api_key: Personal access token to store in the profile.
        endpoint: Roboto API endpoint to store in the profile.
        overwrite: Replace the credentials of an existing profile of the same name, keeping its other settings.
        set_default: Make this profile the default. A newly created file always defaults to its only profile.

    Raises:
        ProfileAlreadyExistsError: The profile exists and ``overwrite`` is false.
        ConfigFileError: The profile name is invalid, the file is not a config file this module can update, or the
            lock could not be acquired.
    """
    _validate_profile_name(profile_name)
    # Write the file a symlink points at: replacing the link itself would detach a dotfiles-managed config.
    config_file = config_file.resolve()

    config_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _write_lock(config_file):
        return _write_profile_locked(config_file, profile_name, api_key, endpoint, overwrite, set_default)


def ensure_profile_org_id_settable(config_file: pathlib.Path, profile_name: typing.Optional[str] = None) -> None:
    """Raise early, without changing anything, for most of the reasons :py:func:`set_profile_org_id` would refuse.

    Lets a caller find out that an organization can't be saved before it asks the user to choose one. Checks that the
    file exists, is a config file this module can update, and has the profile. It takes no lock, so
    :py:func:`set_profile_org_id` can still refuse if the file changes in between.

    Args:
        config_file: Path of the config file.
        profile_name: Profile the caller intends to update. Defaults to the file's default profile.

    Raises:
        ConfigFileError: The file is missing, is not a config file this module can update, or has no such profile.
        OSError: The file could not be read.
    """
    _find_profile(config_file, _read_existing_document(config_file), profile_name)


def set_profile_org_id(
    config_file: pathlib.Path, org_id: str, profile_name: typing.Optional[str] = None
) -> typing.Optional[pathlib.Path]:
    """Set the default organization of one profile in an existing Roboto config file, preserving everything else in it.

    The file is edited as raw JSON, locked, and replaced atomically, as :py:func:`write_profile` does,
    and the result is readable only by its owner. A legacy (V0) file is converted to the V1 format,
    the only one that holds an organization; a copy of the original is kept next to it.

    Args:
        config_file: Path of the config file.
        org_id: Organization the profile's commands act in when the caller names none.
        profile_name: Profile to update. Defaults to the file's default profile.

    Returns:
        Copy of the original file, when a legacy (V0) file was converted to the V1 format. Otherwise ``None``.

    Raises:
        ConfigFileError: The file is missing, is not a config file this module can update, has no such profile,
            or the lock could not be acquired. The file is left untouched.
        OSError: The file could not be read or replaced. The file is left untouched.
    """
    # Write the file a symlink points at: replacing the link itself would detach a dotfiles-managed config.
    config_file = config_file.resolve()

    with _write_lock(config_file):
        document = _read_existing_document(config_file)
        name, profile = _find_profile(config_file, document, profile_name)
        profile["org_id"] = org_id
        if document.v0_text is not None:
            _keep_v0_default_profile(document, otherwise=name)

        _validate_document(config_file, document)
        return _replace_file(config_file, document)


@dataclasses.dataclass
class _Document:
    raw: dict[str, typing.Any]
    """The whole file, as V1. Unknown keys are carried through untouched."""

    v0_text: typing.Optional[str] = None
    """Contents of the V0 file this document was converted from; None when the file was already V1."""

    @property
    def profiles(self) -> dict[str, typing.Any]:
        return self.raw["profiles"]


@contextlib.contextmanager
def _write_lock(config_file: pathlib.Path) -> collections.abc.Iterator[None]:
    """Hold the lock every writer of ``config_file`` takes, so each reads and replaces the file before the next does."""
    try:
        with filelock.FileLock(str(config_file) + ".lock", timeout=_LOCK_TIMEOUT_SECONDS):
            yield
    except filelock.Timeout:
        # The OS releases the lock when its holder exits, so a timeout means another live process holds it.
        raise ConfigFileError(f"Timed out waiting for another process to finish writing '{config_file}'.") from None


def _write_profile_locked(
    config_file: pathlib.Path,
    profile_name: str,
    api_key: str,
    endpoint: str,
    overwrite: bool,
    set_default: bool,
) -> ProfileWriteResult:
    document = _read_document(config_file)
    created_file = document is None
    if document is None:
        document = _Document(raw={"version": "v1", "profiles": {}})

    _raise_if_profile_exists(config_file, document.profiles, profile_name, overwrite)

    profile = document.profiles.get(profile_name)
    if not isinstance(profile, dict):
        profile = {}
    profile["api_key"] = api_key
    profile["endpoint"] = endpoint
    document.profiles[profile_name] = profile

    if created_file or set_default:
        document.raw["default_profile"] = profile_name
    elif document.v0_text is not None:
        _keep_v0_default_profile(document, otherwise=profile_name)

    model = _validate_document(config_file, document)
    v0_backup = _replace_file(config_file, document)

    return ProfileWriteResult(
        config_file=config_file,
        created_file=created_file,
        is_default=(model.default_profile or DEFAULT_ROBOTO_PROFILE_NAME) == profile_name,
        v0_backup=v0_backup,
    )


def _read_existing_document(config_file: pathlib.Path) -> _Document:
    document = _read_document(config_file)
    if document is None:
        raise ConfigFileError(f"'{config_file}' does not exist.")
    return document


def _find_profile(
    config_file: pathlib.Path, document: _Document, profile_name: typing.Optional[str]
) -> tuple[str, dict[str, typing.Any]]:
    """Return the name and contents of the profile ``profile_name``, or of the file's default profile when ``None``."""
    name = profile_name or document.raw.get("default_profile") or DEFAULT_ROBOTO_PROFILE_NAME
    profile = document.profiles.get(name)
    if not isinstance(profile, dict):
        raise ConfigFileError(f"'{config_file}' has no profile '{name}'.")
    return name, profile


def _keep_v0_default_profile(document: _Document, otherwise: str) -> None:
    # V0 readers resolve to the "default" profile; keep that. With no "default" profile, point at ``otherwise``,
    # since a V1 file's default must name an existing profile.
    has_default = DEFAULT_ROBOTO_PROFILE_NAME in document.profiles
    document.raw["default_profile"] = DEFAULT_ROBOTO_PROFILE_NAME if has_default else otherwise


def _replace_file(config_file: pathlib.Path, document: _Document) -> typing.Optional[pathlib.Path]:
    """Write ``document`` to ``config_file``. Returns the copy kept of the original when it was a V0 file."""
    v0_backup = None
    if document.v0_text is not None:
        timestamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        v0_backup = config_file.with_name(f"{config_file.name}.bak-{timestamp}")
        _atomic_write(v0_backup, document.v0_text)

    _atomic_write(config_file, json.dumps(document.raw, indent=2) + "\n")
    return v0_backup


def _validate_document(config_file: pathlib.Path, document: _Document) -> RobotoConfigFileV1:
    try:
        return RobotoConfigFileV1.model_validate(document.raw)
    except pydantic.ValidationError as exc:
        # Leave input values out of the message: for a file-level error the input is the whole file, tokens included.
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'file'}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        )
        raise ConfigFileError(
            f"'{config_file}' would not be a valid config file with this change ({problems})."
        ) from None


def _validate_profile_name(profile_name: str) -> None:
    if not _PROFILE_NAME_PATTERN.fullmatch(profile_name):
        raise ConfigFileError(f"Invalid profile name '{profile_name}': use 1-100 letters, digits, '.', '_' or '-'.")


def _raise_if_profile_exists(
    config_file: pathlib.Path, profiles: dict[str, typing.Any], profile_name: str, overwrite: bool
) -> None:
    if profile_name in profiles and not overwrite:
        raise ProfileAlreadyExistsError(config_file, profile_name, sorted(profiles))


def _read_document(config_file: pathlib.Path) -> typing.Optional[_Document]:
    """Parse the config file into V1 shape, or return None if it does not exist.

    Raises ConfigFileError for anything that is not recognizably a V1 or V0 config, rather than guessing, since
    the caller would otherwise overwrite data it does not understand.
    """
    if not config_file.exists():
        return None

    text = config_file.read_text()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raise ConfigFileError(f"'{config_file}' is not valid JSON.") from None

    if not isinstance(raw, dict):
        raise ConfigFileError(f"'{config_file}' does not contain a JSON object.")

    if "version" in raw:
        if raw["version"] != "v1":
            raise ConfigFileError(f"'{config_file}' has unsupported version {raw['version']!r}.")
        if not isinstance(raw.get("profiles"), dict):
            raise ConfigFileError(f"'{config_file}' has no 'profiles' object.")
        return _Document(raw=raw)

    return _convert_v0(config_file, raw, text)


def _convert_v0(config_file: pathlib.Path, raw: dict[str, typing.Any], text: str) -> _Document:
    profiles: dict[str, typing.Any] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("token"), str):
            raise ConfigFileError(
                f"'{config_file}' is in an older format, and its entry '{name}' cannot be converted to the "
                + "current format."
            )
        profile: dict[str, typing.Any] = {"api_key": entry["token"]}
        if "default_endpoint" in entry:
            profile["endpoint"] = entry["default_endpoint"]
        profiles[name] = profile

    return _Document(raw={"version": "v1", "profiles": profiles}, v0_text=text)


def _atomic_write(path: pathlib.Path, content: str) -> None:
    """Replace ``path`` with ``content`` in one step, leaving the file readable and writable only by its owner."""
    # mkstemp creates the file with mode 0600, and os.replace keeps the temp file's mode.
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        pathlib.Path(tmp_name).unlink(missing_ok=True)
        raise
