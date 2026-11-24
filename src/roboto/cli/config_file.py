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

from ..config import (
    DEFAULT_ROBOTO_PROFILE_NAME,
    ROBOTO_API_ENDPOINT,
    RobotoConfigFileV1,
    resolved_profile_name,
)

_PROFILE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_.\-]{1,100}")
_LOCK_TIMEOUT_SECONDS = 10.0


class ConfigFileError(Exception):
    """The config file cannot be read or updated as asked, and is left untouched.

    Every public function in this module raises it, with a message that says why.
    """


class ProfileAlreadyExistsError(ConfigFileError):
    """The profile to write exists and the caller did not ask to overwrite it.

    ``write_profile`` and ``check_profile_writable`` raise it.
    """

    def __init__(self, config_file: pathlib.Path, profile_name: str, existing_profiles: list[str]) -> None:
        super().__init__(
            f"Profile '{profile_name}' already exists in '{config_file}'. "
            + f"Existing profiles: {', '.join(existing_profiles)}. "
            + "Choose another name with --profile, or pass --overwrite to replace its token and endpoint."
        )
        self.profile_name = profile_name
        self.existing_profiles = existing_profiles


@dataclasses.dataclass(frozen=True)
class ProfileWriteResult:
    """Outcome of a successful ``write_profile`` call."""

    config_file: pathlib.Path
    """Config file the profile was written to, with any symbolic link resolved."""

    created_file: bool
    """Whether the config file did not exist before this write."""

    profile_name: str
    """Profile the token was written to: the one the caller named, or else the file's default profile."""

    is_default: bool
    """Whether the written profile is the file's default, the one used when no profile is selected."""

    v0_backup: typing.Optional[pathlib.Path] = None
    """Copy of the original file, when a file in the earlier format was converted to the ``v1`` format."""


@dataclasses.dataclass(frozen=True)
class WritableProfile:
    """A profile ``check_profile_writable`` found ``write_profile`` could write."""

    exists: bool
    """Whether the file already has the profile."""

    name: str
    """Name of the profile: the one the caller named, or else the file's default profile."""


@dataclasses.dataclass(frozen=True)
class ConfiguredProfiles:
    """Profiles in a config file, and the Roboto API endpoint each one sends requests to."""

    default_profile: str
    """Profile used when none is selected: the file's ``default_profile``, or else ``default``."""

    endpoints: dict[str, str]
    """Endpoint of each profile, without a trailing ``/``.

    A profile that names none uses :py:const:`~roboto.config.ROBOTO_API_ENDPOINT`.
    """


def read_configured_profiles(config_file: pathlib.Path) -> typing.Optional[ConfiguredProfiles]:
    """Read the profiles in the config file and their endpoints, or return ``None`` when the file does not exist.

    A file in the earlier format, with no ``version`` key, is read as ``write_profile`` would convert it, without
    changing the file.

    Raises:
        ConfigFileError: The file is not a config file this module can update.
        OSError: The file could not be read.
    """
    document = _read_document(config_file)
    if document is None:
        return None

    endpoints: dict[str, str] = {}
    for name, profile in document.profiles.items():
        endpoint = profile.get("endpoint") if isinstance(profile, dict) else None
        endpoints[name] = (endpoint if isinstance(endpoint, str) and endpoint else ROBOTO_API_ENDPOINT).rstrip("/")
    return ConfiguredProfiles(default_profile=_profile_name_or_default(document, None), endpoints=endpoints)


def check_profile_writable(
    config_file: pathlib.Path, profile_name: typing.Optional[str], overwrite: bool, set_default: bool = False
) -> WritableProfile:
    """Check, without changing anything, that ``write_profile`` could write the profile now.

    Lets a caller fail before doing work whose result it would then have nowhere to store. Checks the profile name,
    that the file can be read and is in a format this module can update, that an existing profile is replaced only
    with ``overwrite``, and that the file would be valid with the profile written. It takes no lock and writes nothing,
    so ``write_profile`` can still refuse if the file changes in between, if the lock times out, or if the file or its
    directory cannot be written.

    Args:
        config_file: Path of the config file. A missing file passes.
        profile_name: Profile the caller intends to write. Defaults to the file's default profile.
        overwrite: Whether the caller will pass ``overwrite=True`` to ``write_profile``.
        set_default: Whether the caller will pass ``set_default=True`` to ``write_profile``.

    Returns:
        The profile's name, and whether the file already has it.

    Raises:
        ProfileAlreadyExistsError: The profile exists and ``overwrite`` is false.
        ConfigFileError: The profile name is invalid, the file is not a config file this module can update, or the
            file would not be valid with the profile written to it.
        OSError: The file could not be read.
    """
    document = _read_document(config_file)
    name = _profile_name_or_default(document, profile_name)
    exists = document is not None and name in document.profiles
    # Edits the parsed document, which is then discarded. Validity does not depend on the token or endpoint, so
    # placeholders stand in for them.
    _put_profile(config_file, document, name, "api_key", "endpoint", overwrite, set_default)
    return WritableProfile(exists=exists, name=name)


def write_profile(
    config_file: pathlib.Path,
    profile_name: typing.Optional[str],
    api_key: str,
    endpoint: str,
    overwrite: bool,
    set_default: bool = False,
) -> ProfileWriteResult:
    """Add or update one profile in a Roboto config file, preserving everything else in it.

    The file is edited as raw JSON, so profiles, profile settings and top-level keys this version of the SDK does not
    model survive the write. A file in the earlier format, which has no ``version`` key and maps each profile name
    directly to a ``token`` and an optional ``default_endpoint``, is converted to the ``v1`` format; a copy of the
    original is kept next to it, named ``<file name>.bak-<timestamp>``. When ``config_file`` is a symbolic link, the
    file it points to is written and the link is kept.

    The write holds an exclusive lock and replaces the file in one rename, so concurrent logins cannot lose each
    other's profiles and a crash cannot leave a half-written file. The result is readable only by its owner.

    Args:
        config_file: Path of the config file. Created, along with an owner-only parent directory, if missing.
        profile_name: Profile to write. Defaults to the file's default profile: the one its ``default_profile``
            names, or ``default`` when it names none.
        api_key: Personal access token to store in the profile.
        overwrite: Whether to replace the token and endpoint of an existing profile of the same name, keeping its
            other settings.
        set_default: Whether to make this profile the default. A newly created file always defaults to its only
            profile.

    Raises:
        ProfileAlreadyExistsError: The profile exists and ``overwrite`` is false.
        ConfigFileError: The profile name is invalid, the file is not a config file this module can update, or the
            lock could not be acquired.
        OSError: The file could not be read or written, or its directory could not be created.
    """
    if profile_name is not None:
        _validate_profile_name(profile_name)
    # Replacing a symbolic link itself would detach a config file that a dotfiles repository manages.
    config_file = config_file.resolve()

    config_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _write_lock(config_file):
        return _write_profile_locked(config_file, profile_name, api_key, endpoint, overwrite, set_default)


def ensure_profile_org_id_settable(config_file: pathlib.Path, profile_name: typing.Optional[str] = None) -> None:
    """Reject, without changing anything, a config file or profile that ``set_profile_org_id`` would refuse.

    Lets a caller find out that an organization cannot be saved before it asks the user to choose one. Checks that
    the file exists, is a config file this module can update, and has the profile. It takes no lock and writes
    nothing, so ``set_profile_org_id`` can still refuse if the file changes in between, if the lock times out, or if
    the file cannot be replaced.

    Args:
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

    The file is edited as raw JSON, locked, and replaced in one rename, and a symbolic link to it is kept, as
    ``write_profile`` does; the result is readable only by its owner. A file in the earlier format, with no
    ``version`` key, is converted to the ``v1`` format, the only one that holds an organization; a copy of the
    original is kept next to it.

    Args:
        org_id: ID of the organization the profile's commands act in when the caller names none and
            ``ROBOTO_ORG_ID`` is unset.
        profile_name: Profile to update. Defaults to the file's default profile.

    Returns:
        Copy of the original file, when a file in the earlier format was converted to the ``v1`` format. Otherwise
        ``None``.

    Raises:
        ConfigFileError: The file is missing, is not a config file this module can update, has no such profile,
            or the lock could not be acquired.
        OSError: The file could not be read or replaced. The file is left untouched.
    """
    # Replacing a symbolic link itself would detach a config file that a dotfiles repository manages.
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
    """Whole file in the ``v1`` format. Keys the SDK does not model are carried through untouched."""

    v0_text: typing.Optional[str] = None
    """Contents of the earlier-format file this document was converted from, or ``None`` when the file was ``v1``."""

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
    profile_name: typing.Optional[str],
    api_key: str,
    endpoint: str,
    overwrite: bool,
    set_default: bool,
) -> ProfileWriteResult:
    document = _read_document(config_file)
    created_file = document is None
    document, profile_name, model = _put_profile(
        config_file, document, profile_name, api_key, endpoint, overwrite, set_default
    )
    v0_backup = _replace_file(config_file, document)

    return ProfileWriteResult(
        config_file=config_file,
        created_file=created_file,
        profile_name=profile_name,
        is_default=(model.default_profile or DEFAULT_ROBOTO_PROFILE_NAME) == profile_name,
        v0_backup=v0_backup,
    )


def _put_profile(
    config_file: pathlib.Path,
    document: typing.Optional[_Document],
    profile_name: typing.Optional[str],
    api_key: str,
    endpoint: str,
    overwrite: bool,
    set_default: bool,
) -> tuple[_Document, str, RobotoConfigFileV1]:
    """Set the token and endpoint of a profile in ``document``, or in a new document when it is ``None``.

    Points ``default_profile`` at the profile in a new document or with ``set_default``. Otherwise, in a document
    converted from the earlier format, keeps the default on the profile the SDK read from that file. Return the edited
    document, the profile's name, and the document validated as a config file. Raise ``ProfileAlreadyExistsError``
    when the profile exists and ``overwrite`` is false, and ``ConfigFileError`` when the profile name is invalid or the
    document would not be a valid config file.
    """
    profile_name = _profile_name_or_default(document, profile_name)
    _validate_profile_name(profile_name)
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

    return document, profile_name, _validate_document(config_file, document)


def _read_existing_document(config_file: pathlib.Path) -> _Document:
    document = _read_document(config_file)
    if document is None:
        raise ConfigFileError(f"'{config_file}' doesn't exist.")
    return document


def _find_profile(
    config_file: pathlib.Path, document: _Document, profile_name: typing.Optional[str]
) -> tuple[str, dict[str, typing.Any]]:
    """Return the name and contents of the profile ``profile_name``, or of the file's default profile when ``None``."""
    name = _profile_name_or_default(document, profile_name)
    profile = document.profiles.get(name)
    if not isinstance(profile, dict):
        raise ConfigFileError(f"'{config_file}' has no profile '{name}'.")
    return name, profile


def _profile_name_or_default(document: typing.Optional[_Document], profile_name: typing.Optional[str]) -> str:
    """Return ``profile_name``, or when it is ``None`` or empty, the file's ``default_profile``, or else ``default``."""
    return resolved_profile_name(profile_name, document.raw.get("default_profile") if document is not None else None)


def _keep_v0_default_profile(document: _Document, otherwise: str) -> None:
    # A file in the earlier format names no default, so the SDK read its "default" profile; keep that. With no
    # "default" profile, point at otherwise, since a v1 file's default_profile must name an existing profile.
    has_default = DEFAULT_ROBOTO_PROFILE_NAME in document.profiles
    document.raw["default_profile"] = DEFAULT_ROBOTO_PROFILE_NAME if has_default else otherwise


def _replace_file(config_file: pathlib.Path, document: _Document) -> typing.Optional[pathlib.Path]:
    """Write ``document`` to ``config_file``, and return the copy kept of an original in the earlier format."""
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
            f"'{config_file}' wouldn't be a valid config file with this change ({problems})."
        ) from None


def _validate_profile_name(profile_name: str) -> None:
    if not _PROFILE_NAME_PATTERN.fullmatch(profile_name):
        raise ConfigFileError(f"Invalid profile name '{profile_name}': use 1-100 letters, digits, '.', '_', or '-'.")


def _raise_if_profile_exists(
    config_file: pathlib.Path, profiles: dict[str, typing.Any], profile_name: str, overwrite: bool
) -> None:
    if profile_name in profiles and not overwrite:
        raise ProfileAlreadyExistsError(config_file, profile_name, sorted(profiles))


def _read_document(config_file: pathlib.Path) -> typing.Optional[_Document]:
    """Parse the config file into the ``v1`` format, or return ``None`` when it does not exist.

    Raises ``ConfigFileError`` for a file in neither the ``v1`` nor the earlier format, rather than guessing, since the
    caller would otherwise overwrite data it does not understand.
    """
    if not config_file.exists():
        return None

    text = config_file.read_text()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raise ConfigFileError(f"'{config_file}' isn't valid JSON.") from None

    if not isinstance(raw, dict):
        raise ConfigFileError(f"'{config_file}' isn't a JSON object.")

    if "version" in raw:
        if raw["version"] != "v1":
            raise ConfigFileError(f"'{config_file}' has an unsupported version, {raw['version']!r}.")
        if not isinstance(raw.get("profiles"), dict):
            raise ConfigFileError(f"'{config_file}' has no \"profiles\" object.")
        return _Document(raw=raw)

    return _convert_v0(config_file, raw, text)


def _convert_v0(config_file: pathlib.Path, raw: dict[str, typing.Any], text: str) -> _Document:
    profiles: dict[str, typing.Any] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("token"), str):
            raise ConfigFileError(
                f"'{config_file}' has no \"version\" key, and its entry '{name}' can't be converted to the v1 "
                + "format."
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
        # Any failure, an interrupt included, removes the temp file and re-raises.
        pathlib.Path(tmp_name).unlink(missing_ok=True)
        raise
