# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import json
import os
import pathlib
import typing

from ...config import (
    DEFAULT_ROBOTO_PROFILE_NAME,
    ROBOTO_API_ENDPOINT,
    RobotoConfig,
    resolve_config_file,
)
from ...domain.orgs import Org
from ...domain.users import User
from ...env import RobotoEnv, RobotoEnvKey
from ...exceptions import (
    RobotoDeprecatedException,
    RobotoUnauthorizedException,
)
from ...exceptions.domain import RobotoAuthenticationFailureException
from ...http import RobotoClient
from ..auth.profile_store import (
    ConfigFileError,
    ensure_profile_org_id_settable,
    set_profile_org_id,
)
from ..outcome import StepOutcome, StepStatus
from .prompts import (
    Prompts,
    answer_to,
    confirm,
    hidden_answer_to,
)

TOKENS_PAGE_URL = "https://app.roboto.ai/settings/tokens"

TOKEN_PASTE_ATTEMPTS = 3

# What every access token Roboto has issued since March 2024 starts with.
TOKEN_PREFIX = "roboto_pat_"  # noqa: S105

ClientFactory = collections.abc.Callable[[str, str], RobotoClient]
"""Build a client for an ``(endpoint, access token)`` pair."""


@dataclasses.dataclass(frozen=True)
class AccessSetup:
    """What :py:func:`set_up_credentials` found or set up."""

    token: StepOutcome
    """Whether the CLI and SDK have an access token Roboto accepts."""

    organization: typing.Optional[StepOutcome] = None
    """Whether commands know which organization to act in. ``None`` when no token works, since the user's
    organizations can't be listed without one."""

    organization_name: typing.Optional[str] = None
    """Name of the organization commands act in by default, when there is one."""


def set_up_credentials(
    env: RobotoEnv,
    prompts: typing.Optional[Prompts],
    make_client: ClientFactory,
    profile: typing.Optional[str] = None,
    report_token: collections.abc.Callable[[StepOutcome], None] = lambda outcome: None,
) -> AccessSetup:
    """Make sure the CLI and SDK have a working access token and know which organization to act in.

    The token comes from the ``ROBOTO_API_KEY`` or ``ROBOTO_BEARER_TOKEN`` environment variable, or else from the
    Roboto config file (``ROBOTO_CONFIG_FILE`` or ``~/.roboto/config.json``), and is checked against the Roboto API.
    When neither exists and ``prompts`` is given, the user gets ``TOKEN_PASTE_ATTEMPTS`` tries to paste a token, and
    the first one the API accepts is saved to a new config file readable only by them. Where a browser can be opened
    for the user, pressing Enter at the first prompt opens the page that creates tokens; at every other prompt,
    Enter skips the token. An answer that doesn't start with ``roboto_pat_``, as every access token does,
    is never sent to the API.

    ``ROBOTO_ORG_ID``, when set, names the organization commands act in, and one that names none of the user's
    organizations is reported for the user to fix. Without it, commands act in the ``org_id`` of the config file
    profile the token came from. A user in one organization needs none, and a user in several needs one.
    When the profile holds one the user isn't in, or a user in several has none, and ``prompts`` is given,
    the user is asked for a replacement, and the answer is saved as the profile's ``org_id``.
    That is the only change setup ever makes to an existing config file. It keeps everything else in the file
    as it was, except that a file in the format the SDK wrote before July 2024 is converted to the current format,
    which is the only one that holds an organization, and a copy of the original is kept next to it.
    Where the answer couldn't be saved, because the token came from the environment and has no profile, or because
    the file can't be converted, the user is told how to name an organization instead of being asked.

    Args:
        env: Roboto environment variables, read for the token, the config file location, the profile, the API
            endpoint, and the organization.
        prompts: Asks the user for a token and an organization. ``None`` when nobody is at the keyboard, in which
            case a missing token or organization is reported with instructions instead.
        make_client: Builds the client used to check a token.
        profile: Config file profile to check, or to save a pasted token under. Defaults to ``ROBOTO_PROFILE``,
            then to the config file's default profile.
        report_token: Called once with the access token's outcome as soon as it is known, which is before the user
            is asked about an organization.

    Returns:
        The outcome for the access token and, once a token works, the outcome for the organization.
    """
    token = _set_up_token(env, prompts, make_client, profile)
    report_token(token.outcome)
    if token.orgs is None:
        return AccessSetup(token=token.outcome)

    organization, default_org = _set_up_organization(token.orgs, env, token.profile, prompts)
    return AccessSetup(
        token=token.outcome,
        organization=organization,
        organization_name=default_org.name if default_org is not None else None,
    )


def _set_up_token(
    env: RobotoEnv,
    prompts: typing.Optional[Prompts],
    make_client: ClientFactory,
    profile: typing.Optional[str],
) -> _TokenSetup:
    if env.api_key:
        # RobotoEnv reads ROBOTO_API_KEY ahead of ROBOTO_BEARER_TOKEN.
        variable = RobotoEnvKey.ApiKey if RobotoEnvKey.ApiKey in os.environ else RobotoEnvKey.BearerToken
        return _check_existing_token(
            RobotoConfig.from_env(env=env),
            source=f"the {variable.value} environment variable",
            make_client=make_client,
            profile=None,
        )

    config_file = resolve_config_file(env)
    profile_name = profile or env.profile
    if config_file.exists():
        try:
            config = RobotoConfig.from_env(profile_override=profile, env=env)
        except (OSError, ValueError) as exc:
            # from_env raises these for a file it can't read or use, which is a problem for the user to fix.
            return _TokenSetup(
                StepOutcome(
                    step="Access token",
                    status=StepStatus.Failed,
                    summary=f"Couldn't use the config file: {exc}",
                    next_steps=(f"Fix or remove {config_file}, then run `roboto setup` again.",),
                )
            )
        return _check_existing_token(
            config,
            source=str(config_file),
            make_client=make_client,
            profile=_Profile(config_file=config_file, name=profile_name, org_id=config.org_id),
        )

    if prompts is None:
        return _TokenSetup(
            StepOutcome(
                step="Access token",
                status=StepStatus.ActionNeeded,
                summary="No access token found.",
                next_steps=(f"Create one at {TOKENS_PAGE_URL}, then run `roboto setup` in a terminal to paste it.",),
            )
        )

    return _save_pasted_token(
        config_file=config_file,
        endpoint=env.roboto_service_endpoint or ROBOTO_API_ENDPOINT,
        make_client=make_client,
        profile_name=profile_name or DEFAULT_ROBOTO_PROFILE_NAME,
        prompts=prompts,
    )


@dataclasses.dataclass(frozen=True)
class _Identity:
    user: User
    orgs: collections.abc.Sequence[Org]


@dataclasses.dataclass(frozen=True)
class _Profile:
    config_file: pathlib.Path

    name: typing.Optional[str]
    """``None`` for the config file's default profile."""

    org_id: typing.Optional[str]
    """The default organization the profile holds, if it holds one."""


@dataclasses.dataclass(frozen=True)
class _TokenSetup:
    outcome: StepOutcome

    orgs: typing.Optional[collections.abc.Sequence[Org]] = None
    """The organizations the token's user belongs to. ``None`` when no token works."""

    profile: typing.Optional[_Profile] = None
    """The config file profile the token is saved in. ``None`` when no token works, and for a token from the
    environment."""


class _TokenRejected(Exception):
    pass


def _identify(make_client: ClientFactory, endpoint: str, token: str) -> _Identity:
    # Building the client raises RobotoDeprecatedException for a token in the format retired in March 2024. The API
    # refuses any other bad token: its gateway answers with an explicit deny, which the SDK raises as
    # RobotoAuthenticationFailureException, and a 401 or 403 without one is RobotoUnauthorizedException. Any other
    # error propagates.
    try:
        client = make_client(endpoint, token)
        return _Identity(user=User.for_self(roboto_client=client), orgs=Org.for_self(roboto_client=client))
    except (RobotoAuthenticationFailureException, RobotoUnauthorizedException, RobotoDeprecatedException):
        raise _TokenRejected() from None


def _check_existing_token(
    config: RobotoConfig, source: str, make_client: ClientFactory, profile: typing.Optional[_Profile]
) -> _TokenSetup:
    try:
        identity = _identify(make_client, config.endpoint, config.api_key)
    except _TokenRejected:
        return _TokenSetup(
            StepOutcome(
                step="Access token",
                status=StepStatus.ActionNeeded,
                summary=f"Roboto rejected the access token from {source}.",
                next_steps=(f"Replace it with a new one from {TOKENS_PAGE_URL}.",),
            )
        )
    except Exception as exc:
        return _TokenSetup(_token_check_failed_outcome(config.endpoint, exc))

    return _TokenSetup(
        StepOutcome(
            step="Access token",
            status=StepStatus.AlreadyDone,
            summary=f"Signed in as {_describe_user(identity.user)}. Token from {source}.",
        ),
        orgs=identity.orgs,
        profile=profile,
    )


def _save_pasted_token(
    config_file: pathlib.Path,
    endpoint: str,
    make_client: ClientFactory,
    profile_name: str,
    prompts: Prompts,
) -> _TokenSetup:
    print("  Roboto needs an access token.")
    print(f"    1. Create one at {TOKENS_PAGE_URL} (Settings > Tokens).")
    print(f"    2. Copy the value that starts with {TOKEN_PREFIX}.")
    print("    3. Paste it here. It stays hidden.")

    first_prompt = True
    attempts = 0
    while attempts < TOKEN_PASTE_ATTEMPTS:
        open_tokens_page = prompts.open_browser if first_prompt else None
        first_prompt = False
        question = (
            "  Access token (Enter to open the tokens page in your browser): "
            if open_tokens_page is not None
            else "  Access token (Enter to skip): "
        )
        token = hidden_answer_to(prompts, question)
        if not token:
            if open_tokens_page is None:
                break
            if not open_tokens_page(TOKENS_PAGE_URL):
                print("  Couldn't open a browser. Open the address in step 1.")
            continue
        attempts += 1

        if not token.startswith(TOKEN_PREFIX):
            print(f"  That isn't an access token. Paste only the value that starts with {TOKEN_PREFIX}.")
            continue

        try:
            identity = _identify(make_client, endpoint, token)
        except _TokenRejected:
            print("  Roboto rejected that access token. Check that you copied all of it.")
            continue
        except Exception as exc:
            return _TokenSetup(_token_check_failed_outcome(endpoint, exc))

        try:
            _write_new_config_file(config_file, profile=profile_name, token=token, endpoint=endpoint)
        except OSError as exc:
            return _TokenSetup(
                StepOutcome(
                    step="Access token",
                    status=StepStatus.Failed,
                    summary=f"Roboto accepted the token, but setup couldn't save it: {exc}",
                    next_steps=(f"Make sure you can write to {config_file}, then run `roboto setup` again.",),
                )
            )
        return _TokenSetup(
            StepOutcome(
                step="Access token",
                status=StepStatus.Done,
                summary=f"Signed in as {_describe_user(identity.user)}. Saved the token to {config_file}.",
            ),
            orgs=identity.orgs,
            profile=_Profile(config_file=config_file, name=profile_name, org_id=None),
        )

    return _TokenSetup(
        StepOutcome(
            step="Access token",
            status=StepStatus.ActionNeeded,
            summary="No access token saved.",
            next_steps=("Create one, then run `roboto setup` again.",),
        )
    )


def _write_new_config_file(config_file: pathlib.Path, profile: str, token: str, endpoint: str) -> None:
    profile_contents: dict[str, str] = {"api_key": token}
    if endpoint != ROBOTO_API_ENDPOINT:
        profile_contents["endpoint"] = endpoint
    contents = {"version": "v1", "profiles": {profile: profile_contents}, "default_profile": profile}

    config_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Created with owner-only permissions from the start, so the token is never readable by other users, and
    # O_EXCL so a config file that appeared since setup looked is never overwritten.
    fd = os.open(config_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(contents, f, indent=2)
            f.write("\n")
    except BaseException:
        # Setup created the file a moment ago, so removing it after a failed write, or Ctrl-C, loses nothing and
        # leaves no partial config file for the next run to trip over.
        config_file.unlink(missing_ok=True)
        raise


def _set_up_organization(
    orgs: collections.abc.Sequence[Org],
    env: RobotoEnv,
    profile: typing.Optional[_Profile],
    prompts: typing.Optional[Prompts],
) -> tuple[StepOutcome, typing.Optional[Org]]:
    """Work out which of ``orgs`` commands act in by default, asking a member of several with no default to choose.

    ``profile`` is the config file profile the token is saved in, which is where the choice is saved.
    It is ``None`` for a token from the environment, and then the user isn't asked.

    Returns the organization's outcome and, when there is one, the organization commands act in by default.
    """
    if not orgs:
        return (
            StepOutcome(
                step="Organization",
                status=StepStatus.ActionNeeded,
                summary="You don't belong to an organization.",
                next_steps=("Create or join one at https://app.roboto.ai.",),
            ),
            None,
        )

    # What the user is told to set ROBOTO_ORG_ID to.
    if len(orgs) == 1:
        an_org_id = orgs[0].org_id
    else:
        an_org_id = "one of these IDs: " + ", ".join(_describe_org(org) for org in orgs)

    if env.org_id:
        named = next((org for org in orgs if org.org_id == env.org_id), None)
        if named is None:
            return (
                StepOutcome(
                    step="Organization",
                    status=StepStatus.ActionNeeded,
                    summary=f"The ROBOTO_ORG_ID environment variable is {env.org_id}, which isn't one of your "
                    + "organizations.",
                    next_steps=(f"Set it to {an_org_id}.",),
                ),
                None,
            )
        return (
            StepOutcome(
                step="Organization",
                status=StepStatus.AlreadyDone,
                summary=f"{_describe_org(named)}, set by the ROBOTO_ORG_ID environment variable.",
            ),
            named,
        )

    # Commands send the profile's organization ahead of the user's only one, so one the user isn't in has to be
    # replaced even for a member of a single organization.
    saved_org_id = profile.org_id if profile is not None else None
    saved = next((org for org in orgs if org.org_id == saved_org_id), None)
    saved_is_not_theirs = saved_org_id is not None and saved is None

    if len(orgs) == 1 and not saved_is_not_theirs:
        return (
            StepOutcome(
                step="Organization",
                status=StepStatus.AlreadyDone,
                summary=f"{_describe_org(orgs[0])}, your only organization.",
            ),
            orgs[0],
        )

    no_default = f"You belong to {len(orgs)} organizations and have no default."
    set_org_id_variable = f"Set the ROBOTO_ORG_ID environment variable to {an_org_id}."

    if profile is None:
        return (
            StepOutcome(
                step="Organization",
                status=StepStatus.ActionNeeded,
                summary=no_default,
                next_steps=(set_org_id_variable,),
            ),
            None,
        )

    if saved is not None:
        return (
            StepOutcome(
                step="Organization",
                status=StepStatus.AlreadyDone,
                summary=f"{_describe_org(saved)}, your saved default.",
            ),
            saved,
        )

    if saved_is_not_theirs:
        problem = f"Your saved default, {saved_org_id}, isn't one of your organizations."
    else:
        problem = no_default

    try:
        ensure_profile_org_id_settable(profile.config_file, profile.name)
    except (ConfigFileError, OSError) as exc:
        # Raised for a config file a default organization can't be saved in, such as one in the older format with an
        # entry that can't be converted. Asking the user to choose would then end in an answer setup can't keep.
        return (
            StepOutcome(
                step="Organization",
                status=StepStatus.ActionNeeded,
                summary=f"{problem} Setup can't save a default: {exc}",
                next_steps=(set_org_id_variable,),
            ),
            None,
        )

    if prompts is None:
        to_fix_it = "replace it" if saved_is_not_theirs else "choose one"
        return (
            StepOutcome(
                step="Organization",
                status=StepStatus.ActionNeeded,
                summary=problem,
                next_steps=(
                    f"Run `roboto setup` in a terminal to {to_fix_it}, or set the ROBOTO_ORG_ID environment variable "
                    + f"to {an_org_id}.",
                ),
            ),
            None,
        )

    if saved_is_not_theirs:
        print(f"  {problem}")
    if len(orgs) == 1:
        chosen = orgs[0] if confirm(prompts, f"  Replace it with {_describe_org(orgs[0])}?") else None
    else:
        chosen = _ask_for_default_org(orgs, prompts, say_how_many=not saved_is_not_theirs)
    if chosen is None:
        # The user has just read what is wrong on the lines above the question, so the outcome doesn't repeat it.
        if saved_is_not_theirs:
            summary = f"Kept {saved_org_id} as your default."
            next_step = "Run `roboto setup` again to replace it."
        else:
            summary = "No default chosen."
            next_step = "Run `roboto setup` again to choose one."
        return (
            StepOutcome(
                step="Organization",
                status=StepStatus.ActionNeeded,
                summary=summary,
                next_steps=(next_step,),
            ),
            None,
        )

    try:
        legacy_file_copy = set_profile_org_id(profile.config_file, chosen.org_id, profile_name=profile.name)
    except (ConfigFileError, OSError) as exc:
        # set_profile_org_id raises these for a config file it won't or can't update, and leaves the file as it was.
        return (
            StepOutcome(
                step="Organization",
                status=StepStatus.Failed,
                summary=f"Couldn't save {_describe_org(chosen)} as your default: {exc}",
                next_steps=(f"Set the ROBOTO_ORG_ID environment variable to {chosen.org_id}.",),
            ),
            None,
        )
    summary = f"Saved {_describe_org(chosen)} as your default"
    if legacy_file_copy is None:
        summary += "."
    else:
        summary += f" and converted the config file to the current format. The original is at {legacy_file_copy}."
    return (
        StepOutcome(
            step="Organization",
            status=StepStatus.Done,
            summary=summary,
        ),
        chosen,
    )


def _ask_for_default_org(
    orgs: collections.abc.Sequence[Org], prompts: Prompts, say_how_many: bool
) -> typing.Optional[Org]:
    """Ask the user to choose one of ``orgs`` by number, and return it, or ``None`` when they give no answer.

    ``say_how_many`` opens the question with the number of organizations the user belongs to.
    """
    how_many = f"You belong to {len(orgs)} organizations. " if say_how_many else ""
    print(f"  {how_many}Which one should Roboto use by default?")
    for number, org in enumerate(orgs, start=1):
        print(f"    {number}. {_describe_org(org)}")
    numbers = "1 or 2" if len(orgs) == 2 else f"a number from 1 to {len(orgs)}"
    while True:
        answer = answer_to(prompts, f"  Choose {numbers} (Enter to skip): ")
        if not answer:
            return None
        if answer.isdecimal() and 1 <= int(answer) <= len(orgs):
            return orgs[int(answer) - 1]


def _token_check_failed_outcome(endpoint: str, exc: Exception) -> StepOutcome:
    return StepOutcome(
        step="Access token",
        status=StepStatus.Failed,
        summary=f"Couldn't check the access token with Roboto at {endpoint}: {exc}",
        next_steps=("Check your network connection, then run `roboto setup` again.",),
    )


def _describe_org(org: Org) -> str:
    return f"{org.name} ({org.org_id})"


def _describe_user(user: User) -> str:
    return user.name or user.user_id
