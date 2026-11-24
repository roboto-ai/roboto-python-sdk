# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import dataclasses
import getpass
import os
import pathlib
import socket
import sys
import typing

from ...config import (
    ROBOTO_API_ENDPOINT,
    requested_profile_name,
    resolve_config_file,
)
from ...domain.tokens import MAX_CREDENTIAL_REQUEST_TOKEN_EXPIRY_DAYS, TokenRecord
from ...env import RobotoEnvKey
from ...version import __version__
from ..command import RobotoCommand, RobotoCommandSet
from ..config_file import (
    ConfigFileError,
    ProfileWriteResult,
    check_profile_writable,
    read_configured_profiles,
)
from ..context import CLIContext, cli_roboto_env
from ..terminal import print_error_and_exit
from .login_flow import (
    CredentialRequestApi,
    CredentialRequestHttpError,
    LoginError,
    LoginExpiredError,
    LoginOptions,
    LoopbackListenerError,
    TextOutput,
    browser_cannot_reach_loopback,
    open_in_browser,
    parse_token_expiry_days,
    run_login,
)
from .login_target import (
    AmbiguousLoginTargetError,
    LoginCanceledError,
    ask_for_endpoint,
    ask_whether_to_replace_token,
    choose_login_target,
)


@dataclasses.dataclass(frozen=True)
class LoginResult:
    """Result of a successful login: the new access token and the config file profile it was saved to."""

    token: TokenRecord
    profile: ProfileWriteResult


def login_and_save_profile(
    api_endpoint: str,
    options: LoginOptions,
    config_file: pathlib.Path,
    profile_name: typing.Optional[str],
    overwrite: bool,
    set_default: bool,
    open_browser: typing.Callable[[str], bool],
    read_pasted_code: typing.Callable[[], str],
    out: TextOutput,
) -> LoginResult:
    """Sign in through the browser and save the new access token to a config file profile.

    Before it contacts Roboto, refuses an invalid profile name, a config file it cannot update, and an existing
    profile unless ``overwrite`` is set. If saving still fails, deletes the new token from Roboto, authenticating with
    the token itself, as ``IssuedToken`` in ``roboto.cli.auth.login_flow`` describes.

    Args:
        api_endpoint: Roboto API endpoint to sign in to, saved with the token in the profile. Credential requests go
            to the service this endpoint's service discovery document names.
        options: How to create the credential request and receive its authorization code.
        profile_name: Profile to save the token under. ``None`` saves it under the config file's default profile.
        overwrite: Whether to replace the token and endpoint of an existing profile of the same name.
        open_browser: Function that opens a URL in a browser, and returns ``False`` if it could not.
        read_pasted_code: Function that reads an authorization code the user pastes, without echoing it.
        out: Where to print instructions for the user.

    Raises:
        ProfileAlreadyExistsError: The profile exists and ``overwrite`` is false.
        ConfigFileError: The profile name is invalid, or the config file cannot be safely updated.
        OSError: The config file could not be read or written.
        LoginError: Login did not produce a token, for example because the request was denied in the browser or
            expired. Its subclasses in ``roboto.cli.auth.login_flow`` name each cause.
    """
    check_profile_writable(config_file, profile_name, overwrite, set_default)

    with run_login(
        CredentialRequestApi.for_api_endpoint(api_endpoint),
        api_endpoint,
        options,
        open_browser=open_browser,
        read_pasted_code=read_pasted_code,
        out=out,
    ) as token:
        profile = token.save_to_profile(config_file, profile_name, overwrite=overwrite, set_default=set_default)
    return LoginResult(token=token.record, profile=profile)


def login(args, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    """Save a new access token from a browser sign-in to a config file profile, and print the profile and file.

    Also prints a warning to stderr when ``ROBOTO_API_KEY`` or ``ROBOTO_BEARER_TOKEN`` is set, since either one
    overrides the config file. Exits with status 1 when sign-in fails, when the profile cannot be saved, and when
    Ctrl-C, or Ctrl-D at a prompt, cancels it.
    """
    env = cli_roboto_env(args.config_file)
    config_file = resolve_config_file(env)
    overwrite = args.overwrite
    # The prompt is printed to stdout, so asking needs a terminal on both ends.
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if args.choose_endpoint and not interactive:
        print_error_and_exit("--choose-endpoint asks for the endpoint in a terminal. Pass --endpoint instead.")
    try:
        requested_endpoint = (
            ask_for_endpoint(input, sys.stdout)
            if args.choose_endpoint
            else args.endpoint or env.roboto_service_endpoint
        )
        profiles = read_configured_profiles(config_file)
        target = choose_login_target(
            profiles,
            requested_profile=requested_profile_name(args.profile, env),
            requested_endpoint=requested_endpoint,
        )
        profile_name = target.profile_name
        existing_endpoint = profiles.endpoints.get(profile_name) if profiles is not None else None
        # Outside a terminal, an existing profile is left for login_and_save_profile to refuse without `--overwrite`,
        # so scripts keep failing rather than waiting for an answer.
        if existing_endpoint is not None and not overwrite and interactive:
            choice = ask_whether_to_replace_token(
                config_file,
                target,
                existing_endpoint=existing_endpoint,
                set_default=args.set_default,
                ask=input,
                out=sys.stdout,
            )
            profile_name, overwrite = choice.profile_name, choice.overwrite
    except (AmbiguousLoginTargetError, ConfigFileError, OSError) as exc:
        print_error_and_exit(str(exc))
    except (LoginCanceledError, EOFError, KeyboardInterrupt):
        print_error_and_exit("Sign-in canceled. Nothing changed.")

    use_loopback = not args.no_browser and not browser_cannot_reach_loopback(os.environ, sys.platform)
    options = LoginOptions(
        use_loopback=use_loopback,
        loopback_port=args.port,
        expiry_days=args.expiry_days,
        client_hostname=socket.gethostname(),
        client_version=__version__,
    )

    try:
        result = login_and_save_profile(
            target.endpoint,
            options,
            config_file=config_file,
            profile_name=profile_name,
            overwrite=overwrite,
            set_default=args.set_default,
            open_browser=open_in_browser,
            read_pasted_code=lambda: getpass.getpass("Authorization code: "),
            out=sys.stdout,
        )
    except LoopbackListenerError as exc:
        print_error_and_exit(f"{exc} Choose another port with --port, or use --no-browser.")
    except LoginExpiredError as exc:
        print_error_and_exit(
            f"{exc} Run the command again, or use --no-browser to paste the authorization code into the terminal."
        )
    except CredentialRequestHttpError as exc:
        print_error_and_exit(f"Couldn't sign in: {exc}")
    except (ConfigFileError, OSError, LoginError) as exc:
        print_error_and_exit(str(exc))
    except KeyboardInterrupt:
        print_error_and_exit("Sign-in canceled.")

    saved_profile = result.profile.profile_name
    print(
        f"\nSigned in as {result.token.user_id}. Saved the access token to profile '{saved_profile}' in "
        + f"'{result.profile.config_file}'."
    )
    if result.profile.v0_backup is not None:
        print(f"Converted the config file to the v1 format. The original is at '{result.profile.v0_backup}'.")
    if not result.profile.is_default:
        print(
            f"Use the profile with `roboto --profile {saved_profile} ...`, or run the command again with --overwrite "
            + "--set-default to make it the default."
        )
    if env.api_key:
        # RobotoEnv reads ROBOTO_API_KEY ahead of ROBOTO_BEARER_TOKEN.
        variable = RobotoEnvKey.ApiKey if RobotoEnvKey.ApiKey in os.environ else RobotoEnvKey.BearerToken
        print(
            f"Warning: {variable.value} is set in your environment and overrides the config file. Unset it to use "
            + "this profile.",
            file=sys.stderr,
        )


def login_setup_parser(parser: argparse.ArgumentParser) -> None:
    endpoint_choice = parser.add_mutually_exclusive_group()
    endpoint_choice.add_argument(
        "--choose-endpoint",
        action="store_true",
        help=f"Ask for the Roboto API endpoint to sign in to, offering {ROBOTO_API_ENDPOINT}. Use it when your "
        + "organization runs its own Roboto deployment. Needs a terminal.",
    )
    endpoint_choice.add_argument(
        "--endpoint",
        help="Roboto API endpoint to sign in to. Defaults to ROBOTO_SERVICE_ENDPOINT; otherwise, with a profile named, "
        + "to that profile's saved endpoint, and with none named, to the endpoint that every profile in the config "
        + f"file uses; else {ROBOTO_API_ENDPOINT}. With no profile named, the token is saved to the profile that "
        + "already uses this endpoint.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help=(
            "Don't open a browser or listen for its redirect. Print a URL to open on any device, then paste the "
            + "authorization code the page shows. Implied over SSH and on Linux without a display."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Local port for the browser's redirect. Defaults to a free port.",
    )
    parser.add_argument(
        "--expiry-days",
        type=parse_token_expiry_days,
        default=30,
        help=f"Number of days, from 1 to {MAX_CREDENTIAL_REQUEST_TOKEN_EXPIRY_DAYS}, that the new access token stays "
        + "valid. Defaults to %(default)s.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the access token and endpoint of the selected profile if it already exists, without asking. "
        + "Outside a terminal, replacing them requires this flag. The replaced token stays valid.",
    )
    parser.add_argument(
        "--set-default",
        action="store_true",
        help="Make the selected profile the default.",
    )


login_command = RobotoCommand(
    name="login",
    logic=login,
    setup_parser=login_setup_parser,
    requires_config=False,
    command_kwargs={
        "help": (
            "Sign in through your browser and save a new access token to a profile in the Roboto config file. "
            + "Select the profile with the top-level --profile flag (default: ROBOTO_PROFILE, then the profile that "
            + "already uses the endpoint, then the config file's default profile). If the profile already has a "
            + "token, login asks whether to replace it; outside a terminal, replacing it requires --overwrite."
        )
    },
)

command_set = RobotoCommandSet(
    name="auth",
    help="Sign in to Roboto.",
    commands=[login_command],
)
