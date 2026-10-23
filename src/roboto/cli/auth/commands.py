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


@dataclasses.dataclass(frozen=True)
class LoginResult:
    """A token from a successful login and the profile it was saved to."""

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
    """Sign in through the browser and store the new token in a config file profile.

    Before it contacts Roboto, refuses an invalid profile name, a config file it cannot update, and an existing
    profile unless ``overwrite`` is set. If saving still fails, deletion is attempted using the new token's own secret,
    as :py:class:`~roboto.cli.auth.login_flow.IssuedToken` describes.

    Args:
        api_endpoint: Roboto API endpoint the token is used at, saved with it in the profile. Credential requests go
            to the endpoint it names, as :py:meth:`~roboto.cli.auth.login_flow.CredentialRequestApi.for_api_endpoint`
            describes.
        options: How to create the credential request and receive its authorization code.
        config_file: Config file to save the token in.
        profile_name: Profile to save the token under. Defaults to the config file's default profile.
        overwrite: Replace the token and endpoint of an existing profile of the same name.
        set_default: Make the profile the default one.
        open_browser: Opens a URL in a browser; returns False if it could not.
        read_pasted_code: Reads an authorization code pasted by the user, without echoing it.
        out: Where to print instructions for the user.

    Raises:
        ProfileAlreadyExistsError: The profile exists and ``overwrite`` is false.
        ConfigFileError: The config file cannot be safely updated.
        OSError: The config file could not be read or written.
        LoginError: Login did not produce a token.
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
    env = cli_roboto_env(args.config_file)
    config_file = resolve_config_file(env)
    # None leaves write_profile to pick the config file's default profile, the one other commands use.
    profile_name = requested_profile_name(args.profile, env)
    endpoint = (args.endpoint or env.roboto_service_endpoint or ROBOTO_API_ENDPOINT).rstrip("/")

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
            endpoint,
            options,
            config_file=config_file,
            profile_name=profile_name,
            overwrite=args.overwrite,
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
    parser.add_argument(
        "--endpoint",
        help=f"Roboto API endpoint to sign in to. Defaults to ROBOTO_SERVICE_ENDPOINT, or {ROBOTO_API_ENDPOINT}.",
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
        help="Replace the access token and endpoint of the selected profile if it already exists. The replaced token "
        + "stays valid.",
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
            + "Select the profile with the top-level --profile flag (default: ROBOTO_PROFILE, then the config file's "
            + "default profile, then 'default'). Replacing an existing profile's token requires --overwrite."
        )
    },
)

command_set = RobotoCommandSet(
    name="auth",
    help="Sign in to Roboto.",
    commands=[login_command],
)
