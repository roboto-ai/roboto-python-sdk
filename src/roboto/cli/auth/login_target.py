# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import dataclasses
import pathlib
import typing

from ...config import DEFAULT_ROBOTO_PROFILE_NAME, ROBOTO_API_ENDPOINT
from ..config_file import (
    ConfigFileError,
    ConfiguredProfiles,
    ProfileAlreadyExistsError,
    check_profile_writable,
)
from .login_flow import LoginError, TextOutput, check_api_endpoint


class AmbiguousLoginTargetError(Exception):
    """The user named no profile, and the config file has more than one that sign-in could save the token to.

    ``choose_login_target`` raises it.
    """


class LoginCanceledError(Exception):
    """The user canceled sign-in, or ended input, when asked what to do with a profile that already has a token.

    ``ask_whether_to_replace_token`` raises it.
    """


@dataclasses.dataclass(frozen=True)
class LoginTarget:
    """Endpoint that ``roboto auth login`` signs in at, and the profile it saves the new token to."""

    profile_name: str
    """Profile to save the new token to. It may not exist yet."""

    endpoint: str
    """Roboto API endpoint to sign in at, without a trailing ``/``."""


@dataclasses.dataclass(frozen=True)
class ProfileChoice:
    """User's answer to ``ask_whether_to_replace_token``: the profile to save the new token to."""

    profile_name: str
    """Profile to save the new token to: the target profile, or a new one the user named."""

    overwrite: bool
    """Whether the user chose to replace the target profile's token; ``False`` for a new profile."""


def choose_login_target(
    profiles: typing.Optional[ConfiguredProfiles],
    requested_profile: typing.Optional[str],
    requested_endpoint: typing.Optional[str],
) -> LoginTarget:
    """Return the endpoint ``roboto auth login`` signs in at and the profile it saves the new token to.

    - With a profile named, login saves the token to that profile and signs in at ``requested_endpoint``, else at the
      profile's saved endpoint, else at :py:const:`~roboto.config.ROBOTO_API_ENDPOINT`.
    - With only an endpoint named, login signs in there and saves the token to the profile that already uses that
      endpoint: the default profile if it does, else the one other profile that does, else the default profile.
    - With neither named, login saves the token to the default profile and signs in at the endpoint that every
      profile in the config file uses, or at :py:const:`~roboto.config.ROBOTO_API_ENDPOINT` when there are none.

    Args:
        profiles: Profiles in the config file, or ``None`` when there is no config file.
        requested_profile: Profile named by ``--profile`` or ``ROBOTO_PROFILE``. ``None`` or an empty value names none.
        requested_endpoint: Endpoint named by ``--endpoint``, ``--choose-endpoint`` or ``ROBOTO_SERVICE_ENDPOINT``.
            A trailing ``/`` is ignored. ``None`` or an empty value names none.

    Raises:
        AmbiguousLoginTargetError: No profile was named, and two or more profiles other than the default use
            ``requested_endpoint``, or, with no endpoint named either, the profiles use different endpoints.
    """
    endpoint = requested_endpoint.rstrip("/") if requested_endpoint else None
    endpoints = profiles.endpoints if profiles is not None else {}
    default_profile = profiles.default_profile if profiles is not None else DEFAULT_ROBOTO_PROFILE_NAME

    if requested_profile:
        return LoginTarget(requested_profile, endpoint or endpoints.get(requested_profile) or ROBOTO_API_ENDPOINT)

    if endpoint:
        profiles_at_endpoint = sorted(name for name, saved in endpoints.items() if saved == endpoint)
        if not profiles_at_endpoint or default_profile in profiles_at_endpoint:
            return LoginTarget(default_profile, endpoint)
        if len(profiles_at_endpoint) == 1:
            return LoginTarget(profiles_at_endpoint[0], endpoint)
        raise AmbiguousLoginTargetError(
            f"Profiles {', '.join(profiles_at_endpoint)} all use {endpoint}. Choose the one to sign in to with "
            + "--profile."
        )

    distinct_endpoints = sorted(set(endpoints.values()))
    if len(distinct_endpoints) > 1:
        raise AmbiguousLoginTargetError(
            f"The profiles in the config file use different endpoints ({', '.join(distinct_endpoints)}). Choose a "
            + "profile with --profile, or an endpoint with --endpoint."
        )
    return LoginTarget(default_profile, distinct_endpoints[0] if distinct_endpoints else ROBOTO_API_ENDPOINT)


def ask_whether_to_replace_token(
    config_file: pathlib.Path,
    target: LoginTarget,
    existing_endpoint: str,
    set_default: bool,
    ask: typing.Callable[[str], str],
    out: TextOutput,
) -> ProfileChoice:
    """Ask whether to replace the token of the target profile, save to a new profile instead, or cancel.

    An empty answer replaces the token, and any answer other than 1, 2 or 3 repeats the question. The question for a
    new profile's name repeats until the user gives a valid name that no profile has.

    Args:
        target: Login target from ``choose_login_target``, whose profile already exists.
        existing_endpoint: Endpoint the target profile uses now, shown beside the new one when they differ.
        set_default: Whether login will also make the saved profile the default.
        ask: Function that shows a prompt and returns the user's answer, raising ``EOFError`` at end of input.
        out: Stream to print the choices, and the reason a new profile's name was refused, to.

    Raises:
        LoginCanceledError: The user chose to cancel, or ended input.
        OSError: The config file could not be read while checking a new profile's name.
    """
    if existing_endpoint == target.endpoint:
        out.write(f"Profile '{target.profile_name}' already has an access token for {existing_endpoint}.\n")
    else:
        out.write(
            f"Profile '{target.profile_name}' already has an access token for {existing_endpoint}. "
            + f"You're signing in to {target.endpoint}.\n"
        )
    out.write(
        "  1. Replace it with the new token\n" + "  2. Keep it, save the new token to a new profile\n" + "  3. Cancel\n"
    )

    try:
        while True:
            answer = ask("Choose 1, 2 or 3 [1]: ").strip()
            if answer in ("", "1"):
                return ProfileChoice(target.profile_name, overwrite=True)
            if answer == "2":
                return ProfileChoice(_ask_new_profile_name(config_file, set_default, ask, out), overwrite=False)
            if answer == "3":
                raise LoginCanceledError()
    except EOFError:
        raise LoginCanceledError() from None


def _ask_new_profile_name(
    config_file: pathlib.Path, set_default: bool, ask: typing.Callable[[str], str], out: TextOutput
) -> str:
    while True:
        name = ask("Name for the new profile: ").strip()
        if not name:
            continue
        try:
            check_profile_writable(config_file, name, overwrite=False, set_default=set_default)
        except ProfileAlreadyExistsError:
            out.write(f"Profile '{name}' already exists. Choose another name.\n")
            continue
        except ConfigFileError as exc:
            # Usually an invalid name. The file was read without error when the target was chosen, so a refusal of
            # the file itself is rare.
            out.write(f"{exc}\n")
            continue
        return name


def ask_for_endpoint(ask: typing.Callable[[str], str], out: TextOutput) -> str:
    """Ask for the Roboto API endpoint to sign in at, offering :py:const:`~roboto.config.ROBOTO_API_ENDPOINT`.

    An empty answer takes :py:const:`~roboto.config.ROBOTO_API_ENDPOINT`, and an answer without a scheme is read as
    HTTPS. An answer that is neither HTTPS nor HTTP to this machine is refused, and the question repeats.

    Args:
        ask: Function that shows a prompt and returns the user's answer, raising ``EOFError`` at end of input.
        out: Stream to print the reason an answer was refused to.

    Returns:
        Endpoint, without a trailing ``/``.

    Raises:
        EOFError: Input ended before an endpoint was given.
    """
    while True:
        answer = ask(f"Roboto API endpoint, as your Roboto contact gave it to you [{ROBOTO_API_ENDPOINT}]: ").strip()
        endpoint = (answer if "://" in answer else f"https://{answer}") if answer else ROBOTO_API_ENDPOINT
        try:
            check_api_endpoint(endpoint)
        except LoginError as exc:
            out.write(f"{exc}\n")
            continue
        return endpoint.rstrip("/")
