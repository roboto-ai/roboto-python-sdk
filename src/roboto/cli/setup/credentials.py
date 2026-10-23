# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import os
import pathlib
import socket
import sys
import typing

from ...config import (
    DEFAULT_ROBOTO_CONFIG_DIR,
    ROBOTO_API_ENDPOINT,
    RobotoConfig,
    requested_profile_name,
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
from ...version import __version__
from ..auth.login_flow import (
    BrowserSignInUnsupportedError,
    CredentialRequestApi,
    LoginDeniedError,
    LoginError,
    LoginOptions,
    run_login,
)
from ..config_file import (
    ConfigFileError,
    check_profile_writable,
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

DEFAULT_SETUP_TOKEN_EXPIRY_DAYS = 180
"""Number of days an access token from setup's sign-in stays valid, unless the caller asks for another number."""

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
    token_expiry_days: int = DEFAULT_SETUP_TOKEN_EXPIRY_DAYS,
) -> AccessSetup:
    """Make sure the CLI and SDK have a working access token and know which organization to act in.

    The token comes from the ``ROBOTO_API_KEY`` or ``ROBOTO_BEARER_TOKEN`` environment variable, or else from a
    profile in the Roboto config file (``ROBOTO_CONFIG_FILE`` or ``~/.roboto/config.json``), and is checked against the
    Roboto API. A token from the environment is only checked. Otherwise, when the file doesn't exist, lacks the
    profile, or holds a token the API rejects, and ``prompts`` is given, the user is asked whether to sign in
    through the browser, as ``roboto auth login`` does. Where no browser can be opened for the user, setup prints
    the approval page's address for them to open on any device, and reads the authorization code that page shows.
    The new token is checked, then saved to the profile: a rejected token is replaced, and the profile's other
    settings are kept. A new file is readable only by the user. Nothing is sent to Roboto to sign in unless the user
    agrees, and a token setup can't check or save is deleted.

    ``ROBOTO_ORG_ID``, when set, names the organization commands act in, and one that names none of the user's
    organizations is reported for the user to fix. Without it, commands act in the ``org_id`` of the config file
    profile the token came from. A user in one organization needs none, and a user in several needs one.
    When the profile holds one the user isn't in, or a user in several has none, and ``prompts`` is given,
    the user is asked for a replacement, and the answer is saved as the profile's ``org_id``.
    Apart from a token from a sign-in, that is the only change setup makes to an existing config file. Either change
    keeps everything else in the file as it was, except that a file in the format the SDK wrote before July 2024 is
    converted to the current format, which is the only one that holds an organization, and a copy of the original is
    kept next to it.
    Where the answer couldn't be saved, because the token came from the environment and has no profile, or because
    the file can't be converted, the user is told how to name an organization instead of being asked.

    Args:
        env: Roboto environment variables, read for the token, the config file location, the profile, the API
            endpoint, and the organization.
        prompts: Asks the user whether to sign in, and which organization to use. ``None`` when nobody is at the
            keyboard, in which case a missing token or organization is reported with instructions instead.
        make_client: Builds the client used to check a token.
        profile: Config file profile to check, or to save a new token under. Defaults to ``ROBOTO_PROFILE``,
            then to the config file's default profile.
        report_token: Called once with the access token's outcome as soon as it is known, which is before the user
            is asked about an organization.
        token_expiry_days: Number of days a token from a sign-in stays valid.

    Returns:
        The outcome for the access token and, once a token works, the outcome for the organization.
    """
    token = _set_up_token(env, prompts, make_client, profile, token_expiry_days)
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
    token_expiry_days: int,
) -> _TokenSetup:
    if env.api_key:
        # RobotoEnv reads ROBOTO_API_KEY ahead of ROBOTO_BEARER_TOKEN.
        variable = RobotoEnvKey.ApiKey if RobotoEnvKey.ApiKey in os.environ else RobotoEnvKey.BearerToken
        source = f"the {variable.value} environment variable"
        config = RobotoConfig.from_env(env=env)
        try:
            return _check_existing_token(config, source, make_client, profile=None)
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

    sign_in = _SignIn(
        config_file=resolve_config_file(env),
        profile_name=requested_profile_name(profile, env),
        prompts=prompts,
        make_client=make_client,
        expiry_days=token_expiry_days,
        new_profile_endpoint=(env.roboto_service_endpoint or ROBOTO_API_ENDPOINT).rstrip("/"),
    )
    if not sign_in.config_file.exists():
        return sign_in.offer(problem=None, endpoint=sign_in.new_profile_endpoint, org_id=None, replacing=False)

    try:
        config = RobotoConfig.from_env(profile_override=profile, env=env)
    except (OSError, ValueError) as exc:
        # from_env raises these for a file it can't read or use, which is a problem for the user to fix, and for a
        # file that lacks the profile, which a sign-in adds.
        missing_profile = sign_in.missing_profile()
        if missing_profile is not None:
            return sign_in.offer(
                problem=f"'{sign_in.config_file}' has no profile '{missing_profile}'.",
                endpoint=sign_in.new_profile_endpoint,
                org_id=None,
                replacing=False,
            )
        return _TokenSetup(
            StepOutcome(
                step="Access token",
                status=StepStatus.Failed,
                summary=f"Couldn't use the config file: {exc}",
                next_steps=(f"Fix or remove '{sign_in.config_file}', then run `roboto setup` again.",),
            )
        )

    profile_in_file = _Profile(config_file=sign_in.config_file, name=sign_in.profile_name, org_id=config.org_id)
    try:
        return _check_existing_token(config, f"'{sign_in.config_file}'", make_client, profile=profile_in_file)
    except _TokenRejected:
        return sign_in.offer(
            problem=f"Roboto rejected the access token from '{sign_in.config_file}'.",
            endpoint=config.endpoint,
            org_id=config.org_id,
            replacing=True,
        )
    except Exception as exc:
        return _TokenSetup(_token_check_failed_outcome(config.endpoint, exc))


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
    """Check the token in ``config``, which came from ``source``, and return its outcome when Roboto accepts it.

    Raises:
        _TokenRejected: Roboto rejected the token. Any other error from checking it propagates.
    """
    identity = _identify(make_client, config.endpoint, config.api_key)
    return _TokenSetup(
        StepOutcome(
            step="Access token",
            status=StepStatus.AlreadyDone,
            summary=f"Signed in as {_describe_user(identity.user)} with the access token from {source}.",
        ),
        orgs=identity.orgs,
        profile=profile,
    )


@dataclasses.dataclass(frozen=True)
class _SignIn:
    """Signing in through the browser to save a new token to the config file profile setup reads."""

    config_file: pathlib.Path

    profile_name: typing.Optional[str]
    """The profile named by ``--profile`` or ``ROBOTO_PROFILE``. ``None`` for the config file's default profile."""

    prompts: typing.Optional[Prompts]
    make_client: ClientFactory
    expiry_days: int

    new_profile_endpoint: str
    """Roboto API endpoint a new profile is saved with: ``ROBOTO_SERVICE_ENDPOINT``, or else Roboto's own. ``roboto
    auth login`` signs in to it too, unless given ``--endpoint``."""

    def missing_profile(self) -> typing.Optional[str]:
        """Return the name of the profile setup reads when the config file lacks it and a sign-in could add it."""
        try:
            profile = check_profile_writable(self.config_file, self.profile_name, overwrite=True)
        except (ConfigFileError, OSError):
            return None
        return None if profile.exists else profile.name

    def offer(
        self, problem: typing.Optional[str], endpoint: str, org_id: typing.Optional[str], replacing: bool
    ) -> _TokenSetup:
        """Ask the user whether to sign in, and sign them in when they agree.

        Asks nothing when nobody is at the keyboard, or when the profile can't take a new token, and returns a step
        for the user instead.

        Args:
            problem: Why the config file gave setup no token Roboto accepts, printed before the question and used as
                the outcome's summary when nothing is asked. ``None`` when there is no config file.
            endpoint: Roboto API endpoint to sign in to, and to save in the profile.
            org_id: The default organization the profile holds, which the organization step starts from.
            replacing: The profile exists, and its token is replaced.
        """
        summary = problem or "No access token found."
        try:
            check_profile_writable(self.config_file, self.profile_name, overwrite=replacing)
        except (ConfigFileError, OSError) as exc:
            # Raised for a profile a token can't be saved in, such as one in a config file in the older format with an
            # entry that can't be converted. Signing in would then issue a token that setup couldn't keep.
            if replacing:
                next_step = f"Replace the rejected token in '{self.config_file}' with a new one from {TOKENS_PAGE_URL}."
            else:
                next_step = f"Fix the profile name or '{self.config_file}', then run `roboto setup` again."
            return _TokenSetup(
                StepOutcome(
                    step="Access token",
                    status=StepStatus.ActionNeeded,
                    summary=f"{summary} Setup can't save a new access token: {exc}",
                    next_steps=(next_step,),
                )
            )

        login_command = self.__login_command(endpoint, replacing)
        if self.prompts is None:
            return _TokenSetup(
                StepOutcome(
                    step="Access token",
                    status=StepStatus.ActionNeeded,
                    summary=summary,
                    next_steps=(f"Sign in with `{login_command}`, then run `roboto setup` again.",),
                )
            )

        if problem is not None:
            print(f"  {problem}")
        question = (
            "  Sign in to Roboto through your browser to replace it?"
            if replacing
            else "  Sign in to Roboto through your browser?"
        )
        if not confirm(self.prompts, question):
            # Any problem was printed on the line above the question, so the outcome doesn't repeat it.
            return _TokenSetup(
                StepOutcome(
                    step="Access token",
                    status=StepStatus.ActionNeeded,
                    summary="Kept the rejected token." if replacing else "No access token saved.",
                    next_steps=(f"Run `roboto setup` again, or `{login_command}`, to sign in.",),
                )
            )

        return self.__sign_in(self.prompts, endpoint, org_id, replacing)

    def __sign_in(self, prompts: Prompts, endpoint: str, org_id: typing.Optional[str], replacing: bool) -> _TokenSetup:
        options = LoginOptions(
            use_loopback=prompts.open_browser is not None,
            loopback_port=0,
            expiry_days=self.expiry_days,
            client_hostname=socket.gethostname(),
            client_version=__version__,
        )
        try:
            token = run_login(
                CredentialRequestApi.for_api_endpoint(endpoint),
                endpoint,
                options,
                # Without a browser to open, options.use_loopback is false and run_login never calls this.
                open_browser=prompts.open_browser or (lambda url: False),
                read_pasted_code=lambda: hidden_answer_to(prompts, "  Authorization code: "),
                out=_IndentedLines(sys.stdout, indent="  "),
            )
        except LoginDeniedError:
            return _TokenSetup(
                StepOutcome(
                    step="Access token",
                    status=StepStatus.ActionNeeded,
                    summary="You denied the sign-in in the browser.",
                    next_steps=("Run `roboto setup` again to sign in.",),
                )
            )
        except BrowserSignInUnsupportedError:
            return _TokenSetup(
                StepOutcome(
                    step="Access token",
                    status=StepStatus.ActionNeeded,
                    summary=f"Roboto at {endpoint} doesn't support signing in through the browser.",
                    next_steps=(
                        "Create an access token in the Roboto web app under Settings > Tokens, save it in "
                        + f"'{self.config_file}', then run `roboto setup` again.",
                    ),
                )
            )
        except LoginError as exc:
            return _TokenSetup(
                StepOutcome(
                    step="Access token",
                    status=StepStatus.Failed,
                    summary=f"Couldn't sign in: {exc}",
                    next_steps=("Run `roboto setup` again to sign in.",),
                )
            )

        # Leaving the block without saving the token deletes it, or tells the user how to when deleting fails, for a
        # token Roboto rejects, one setup can't check, and one setup can't save.
        with token:
            try:
                identity = _identify(self.make_client, endpoint, token.secret)
            except _TokenRejected:
                return _TokenSetup(
                    StepOutcome(
                        step="Access token",
                        status=StepStatus.Failed,
                        summary="Roboto rejected the new access token.",
                        next_steps=("Run `roboto setup` again to sign in.",),
                    )
                )
            except Exception as exc:
                return _TokenSetup(_token_check_failed_outcome(endpoint, exc))

            try:
                saved = token.save_to_profile(self.config_file, self.profile_name, overwrite=replacing)
            except (ConfigFileError, OSError) as exc:
                return _TokenSetup(
                    StepOutcome(
                        step="Access token",
                        status=StepStatus.Failed,
                        summary=f"Signed in, but setup couldn't save the new access token: {exc}",
                        next_steps=(
                            f"Make sure you can write to '{self.config_file}', then run `roboto setup` again.",
                        ),
                    )
                )

        summary = f"Signed in as {_describe_user(identity.user)}. Saved the access token to '{self.config_file}'"
        if saved.v0_backup is None:
            summary += "."
        else:
            summary += f" and converted the config file to the v1 format. The original is at '{saved.v0_backup}'."
        return _TokenSetup(
            StepOutcome(step="Access token", status=StepStatus.Done, summary=summary),
            orgs=identity.orgs,
            profile=_Profile(config_file=self.config_file, name=self.profile_name, org_id=org_id),
        )

    def __login_command(self, endpoint: str, replacing: bool) -> str:
        """Return the ``roboto auth login`` command that signs in to ``endpoint`` and saves the token where setup
        would have saved it."""
        config_file_option = (
            f"--config-file {self.config_file} " if self.config_file != DEFAULT_ROBOTO_CONFIG_DIR else ""
        )
        profile_option = f"--profile {self.profile_name} " if self.profile_name is not None else ""
        endpoint_option = f" --endpoint {endpoint}" if endpoint != self.new_profile_endpoint else ""
        overwrite_option = " --overwrite" if replacing else ""
        return f"roboto {config_file_option}{profile_option}auth login{endpoint_option}{overwrite_option}"


class _IndentedLines:
    """Write to ``stream``, starting each line that holds text with ``indent``."""

    def __init__(self, stream: typing.TextIO, indent: str) -> None:
        self.__stream = stream
        self.__indent = indent
        self.__at_line_start = True

    def write(self, text: str) -> int:
        for line in text.splitlines(keepends=True):
            if self.__at_line_start and line.strip():
                self.__stream.write(self.__indent)
            self.__stream.write(line)
            self.__at_line_start = line.endswith("\n")
        return len(text)

    def flush(self) -> None:
        self.__stream.flush()


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
        summary += f" and converted the config file to the v1 format. The original is at '{legacy_file_copy}'."
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
