# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import argparse
import collections.abc
import contextlib
import dataclasses
import datetime
import http
import pathlib
import sys
import typing
import urllib.error
import urllib.parse
import webbrowser

from ...domain.tokens import (
    MAX_CREDENTIAL_REQUEST_TOKEN_EXPIRY_DAYS,
    CreateCredentialRequest,
    CreateCredentialRequestResult,
    ExchangeCredentialRequestCode,
    Token,
    TokenRecord,
)
from ...exceptions import HttpError, RobotoDomainException
from ...http import (
    BearerTokenDecorator,
    HttpClient,
    HttpClientOptions,
    HttpRequest,
    HttpRetryOptions,
    RobotoClient,
    RobotoRequester,
    RobotoTool,
    is_expected_to_be_transient,
)
from ...service_discovery import (
    SERVICE_DISCOVERY_PATH,
    ServiceDiscoveryDocument,
)
from ..config_file import ProfileWriteResult, write_profile
from .loopback import LoginTimeoutError, LoopbackCallbackServer
from .pkce import PkcePair, generate_state

_LOCAL_DEVELOPMENT_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class TextOutput(typing.Protocol):
    """Where login prints its instructions for the user, such as :py:data:`sys.stdout`."""

    def flush(self) -> object: ...

    def write(self, text: str, /) -> object: ...


class LoginError(Exception):
    """Login did not produce a token."""


class LoginDeniedError(LoginError):
    """The user denied the credential request in the browser."""


class LoginExpiredError(LoginError):
    """The credential request expired before the browser approved or denied it."""


class LoopbackListenerError(LoginError):
    """The listener for the browser's redirect could not bind to its port on 127.0.0.1."""


class NoAuthorizationCodeError(LoginError):
    """The user entered no authorization code."""


class BrowserSignInUnsupportedError(LoginError):
    """The Roboto API names no credential request service, so the CLI can't sign in through the browser.

    A Roboto deployment that predates browser sign-in has no service discovery document and refuses the lookup with HTTP
    401. A deployment that serves the document but doesn't offer browser sign-in leaves ``credential_requests.v1`` out
    of it.
    """


class CredentialRequestHttpError(LoginError):
    """Roboto, or a gateway or proxy in front of it, answered a credential request call with an HTTP error status."""


class CredentialRequestRateLimitedError(CredentialRequestHttpError):
    """Roboto answered a credential request call with HTTP 429: too many sign-in requests came from this network."""


class CredentialRequestNoResponseError(LoginError):
    """A credential request call got no HTTP response.

    The connection failed, or broke or timed out before the response arrived. The call may have reached Roboto.
    """


class CredentialRequestApi:
    """Unauthenticated HTTP adapter for creating requests and exchanging authorization codes.

    Neither call retries HTTP 429. Exchange also does not retry lost responses, connection failures, timeouts, or HTTP
    408/500/504. DNS failures and HTTP 502/503 retain the SDK's retries.
    """

    @classmethod
    def for_api_endpoint(cls, api_endpoint: str) -> CredentialRequestApi:
        """Return an adapter for the credential request service the Roboto API at ``api_endpoint`` names.

        The lookup fetches the deployment's :py:class:`~roboto.service_discovery.ServiceDiscoveryDocument`, with the
        SDK's retries. It and the adapter's requests carry no credentials, and identify the CLI as their source.

        Raises:
            BrowserSignInUnsupportedError: The Roboto API refused the lookup with HTTP 401, or its service discovery
                document names no credential request service.
            CredentialRequestHttpError: The Roboto API, or a gateway or proxy in front of it, answered the lookup with
                another HTTP error status.
            CredentialRequestNoResponseError: No HTTP response to the lookup arrived.
            LoginError: The lookup's response isn't a service discovery document, or the endpoint the Roboto API named
                is neither HTTPS nor HTTP to this machine.
        """
        # The lookup goes through an HttpClient because the HttpError it raises keeps the response's status. That status
        # separates a deployment without the service discovery document, whose authorizer answers 401 to a request
        # without a token, from a refusal such as a proxy's 403. RobotoClient raises a 401 and a 403 as the same
        # exception.
        lookup_client = HttpClient(requester=RobotoRequester.for_tool(RobotoTool.Cli))
        with _raising_login_errors(api_endpoint):
            try:
                response = lookup_client.get(f"{api_endpoint.rstrip('/')}{SERVICE_DISCOVERY_PATH}")
            except HttpError as exc:
                if exc.status != http.HTTPStatus.UNAUTHORIZED:
                    # Translated as RobotoClient translates the other calls' errors, so _raising_login_errors words it
                    # the same way.
                    raise RobotoDomainException.from_client_error(exc) from None
                # A deployment without the document offers no credential request service.
                document = ServiceDiscoveryDocument()
            else:
                try:
                    document = response.to_record(ServiceDiscoveryDocument, json_path=None)
                except ValueError:
                    # Each way the body can fail to be a service discovery document raises a ValueError: a
                    # UnicodeDecodeError or JSONDecodeError for a body that isn't JSON, such as a captive portal's
                    # sign-in page, or a pydantic ValidationError for JSON that isn't an object or whose
                    # credential_requests.v1 isn't a string. A failure to read the body isn't a ValueError, so it
                    # reaches _raising_login_errors.
                    raise LoginError(
                        f"The response from {api_endpoint} didn't come from Roboto. If this network has a sign-in "
                        + "page, sign in to it and try again. Otherwise, check the endpoint."
                    ) from None
        if document.credential_requests_v1 is None:
            raise BrowserSignInUnsupportedError(
                f"Roboto at {api_endpoint} doesn't support signing in through the browser. Create an access token in "
                + "the Roboto web app under Settings > Tokens instead."
            )
        endpoint = document.credential_requests_v1.rstrip("/")
        _check_sign_in_url(endpoint)
        return cls(
            RobotoClient(
                endpoint=endpoint,
                auth_decorator=None,
                http_client_kwargs={
                    "requester": RobotoRequester.for_tool(RobotoTool.Cli),
                    "options": HttpClientOptions(retry=HttpRetryOptions(predicate=_is_transient_unless_rate_limited)),
                },
            )
        )

    def __init__(self, roboto_client: RobotoClient) -> None:
        self.__client = roboto_client

    @property
    def endpoint(self) -> str:
        """Base URL this adapter sends credential requests to."""
        return self.__client.endpoint

    def create_request(self, request: CreateCredentialRequest) -> CreateCredentialRequestResult:
        """Create a credential request for the user to approve or deny in the browser.

        Args:
            request: The challenge derived from the CLI's verifier, the new token's lifetime, where to redirect the
                browser, if anywhere, and what the approval page shows the user.

        Raises:
            CredentialRequestHttpError: Roboto, or a gateway or proxy in front of it, answered with an HTTP error
                status.
            CredentialRequestNoResponseError: No HTTP response arrived.
        """
        with _raising_login_errors(self.endpoint):
            return self.__client.post("v1/tokens/requests", data=request).to_record(CreateCredentialRequestResult)

    def exchange_code(self, request: ExchangeCredentialRequestCode) -> TokenRecord:
        """Redeem the code for a token, including its secret.

        A lost successful response leaves the issued secret unavailable; exchanging again cannot recover it.

        Args:
            request: The approved request's authorization code and the requesting CLI's verifier.

        Raises:
            CredentialRequestHttpError: Roboto, or a gateway or proxy in front of it, answered with an HTTP error
                status.
            CredentialRequestNoResponseError: No HTTP response arrived.
        """
        with _raising_login_errors(self.endpoint):
            return self.__client.post("v1/tokens/requests/exchange", data=request, idempotent=False).to_record(
                TokenRecord
            )


def _is_transient_unless_rate_limited(request: HttpRequest, exc: BaseException) -> bool:
    """Retry predicate: the SDK's default, except that HTTP 429 is never retried.

    A deployment can limit how many credential requests one IP address sends, and answers requests past the limit with
    HTTP 429. Retrying them through the SDK's backoff would only keep the CLI waiting, up to about two and a half
    minutes, before it fails.
    """
    if isinstance(exc, urllib.error.HTTPError) and exc.code == http.HTTPStatus.TOO_MANY_REQUESTS:
        return False
    return is_expected_to_be_transient(request, exc)


@contextlib.contextmanager
def _raising_login_errors(endpoint: str) -> collections.abc.Iterator[None]:
    """Re-raise the HTTP and connection failures of a call to ``endpoint`` as login errors.

    HTTP 429 becomes :py:class:`CredentialRequestRateLimitedError`, another HTTP error status
    :py:class:`CredentialRequestHttpError`, and a missing response :py:class:`CredentialRequestNoResponseError`. Other
    errors pass through.

    Every message but the one for HTTP 429 names ``endpoint``. A missing response's message also says to allow its host,
    since a network or sandbox that limits which domains it reaches may allow the Roboto API's host but not the host
    that serves credential requests.
    """
    host = urllib.parse.urlsplit(endpoint).hostname
    unreachable_hint = f"If this network or sandbox limits which domains it can reach, it must allow {host}."
    try:
        yield
    except (RobotoDomainException, HttpError) as exc:
        # RobotoClient, and for_api_endpoint for its lookup, raise an error response as a RobotoDomainException, or as
        # the HttpError itself for a status with no such exception, such as 408 or 429.
        if isinstance(exc, HttpError) and exc.status == http.HTTPStatus.TOO_MANY_REQUESTS:
            raise CredentialRequestRateLimitedError(
                "Too many sign-in attempts from this network. Try again in a few minutes."
            ) from None
        raise CredentialRequestHttpError(f"Roboto at {endpoint} refused the request: {exc}") from None
    except urllib.error.URLError as exc:
        raise CredentialRequestNoResponseError(
            f"No response from Roboto at {endpoint}: {exc.reason}. {unreachable_hint}"
        ) from None
    except (ConnectionError, TimeoutError) as exc:
        # None of these is a URLError: a refused connection arrives as a bare ConnectionRefusedError, a connection
        # reset while reading the response as a ConnectionResetError, and a read that times out as a TimeoutError.
        raise CredentialRequestNoResponseError(
            f"No response from Roboto at {endpoint}: {exc}. {unreachable_hint}"
        ) from None


@dataclasses.dataclass(frozen=True)
class LoginOptions:
    """Settings for one run of :py:func:`run_login`."""

    use_loopback: bool
    """Receive the authorization code through a local redirect. Otherwise the user pastes it from the browser."""

    loopback_port: int
    """Port for the local listener; 0 picks a free one."""

    expiry_days: int
    """Number of days the new token stays valid."""

    client_hostname: str
    """Name of this machine, shown on the approval page so the user can recognize the request."""

    client_version: str
    """Version of this CLI, shown on the approval page."""


def parse_token_expiry_days(arg: str) -> int:
    """argparse ``type`` for the number of days the access token from a browser sign-in stays valid.

    A value that is not a whole number from 1 to
    :py:data:`~roboto.domain.tokens.MAX_CREDENTIAL_REQUEST_TOKEN_EXPIRY_DAYS` ends argument parsing with
    ``error: argument <flag>: must be a whole number from 1 to <maximum>``, before the CLI contacts Roboto.

    Args:
        arg: Value argparse read for the flag.

    Returns:
        The number of days.

    Raises:
        argparse.ArgumentTypeError: If ``arg`` is not a whole number from 1 to the maximum.
    """
    message = f"must be a whole number from 1 to {MAX_CREDENTIAL_REQUEST_TOKEN_EXPIRY_DAYS}"
    try:
        days = int(arg)
    except ValueError:
        raise argparse.ArgumentTypeError(message) from None
    if not 1 <= days <= MAX_CREDENTIAL_REQUEST_TOKEN_EXPIRY_DAYS:
        raise argparse.ArgumentTypeError(message)
    return days


class IssuedToken:
    """A token :py:func:`run_login` issued, which is deleted unless it is saved to a config file profile.

    Use it as a context manager. Unless :py:meth:`save_to_profile` returns before the ``with`` block ends, the token is
    deleted when the block ends, whatever ends it, Ctrl-C included. The deletion is reported on stderr. So is a failure
    to delete, along with how to delete the token by hand; that failure never replaces an exception that ended the
    block.
    """

    def __init__(self, record: TokenRecord, endpoint: str) -> None:
        self.__record = record
        self.__endpoint = endpoint
        self.__saved = False

    def __enter__(self) -> IssuedToken:
        return self

    def __exit__(self, *exc_info: object) -> None:
        if not self.__saved:
            self.__delete()

    @property
    def record(self) -> TokenRecord:
        """The token as Roboto issued it, including its secret."""
        return self.__record

    @property
    def secret(self) -> str:
        """The token's secret, which authenticates requests to Roboto."""
        # run_login raises LoginError instead of returning a token without a secret.
        return typing.cast(str, self.__record.secret)

    def save_to_profile(
        self,
        config_file: pathlib.Path,
        profile_name: typing.Optional[str],
        overwrite: bool,
        set_default: bool = False,
    ) -> ProfileWriteResult:
        """Save the token and the Roboto API endpoint it is used at to a config file profile, through
        :py:func:`write_profile`.

        Args:
            config_file: Config file to save the token in.
            profile_name: Profile to save the token under. Defaults to the config file's default profile.
            overwrite: Replace the token and endpoint of an existing profile of the same name.
            set_default: Make the profile the default one.

        Raises:
            ProfileAlreadyExistsError: The profile exists and ``overwrite`` is false.
            ConfigFileError: The config file cannot be safely updated.
            OSError: The config file could not be read or written, or its directory could not be created.
        """
        result = write_profile(
            config_file,
            profile_name,
            api_key=self.secret,
            endpoint=self.__endpoint,
            overwrite=overwrite,
            set_default=set_default,
        )
        self.__saved = True
        return result

    def __delete(self) -> None:
        try:
            client = RobotoClient(endpoint=self.__endpoint, auth_decorator=BearerTokenDecorator(self.secret))
            Token(record=self.__record, roboto_client=client).delete()
            print("Deleted the new access token because it wasn't saved.", file=sys.stderr)
        except BaseException:
            # Cleanup errors, including cancellation, must not replace whatever ended the block.
            context = self.__record.context
            if context is None:
                how_to_delete = "Delete it in Settings > Tokens."
            else:
                how_to_delete = (
                    f"Delete '{context.name}' in Settings > Tokens, or run "
                    + f"`roboto tokens delete --id {context.token_id}`."
                )
            print(f"Couldn't delete the new access token, which wasn't saved. {how_to_delete}", file=sys.stderr)


def open_in_browser(url: str) -> bool:
    """Open ``url`` in the user's browser, and return whether one opened."""
    try:
        return webbrowser.open(url)
    except webbrowser.Error:
        return False


def browser_cannot_reach_loopback(environ: collections.abc.Mapping[str, str], platform: str) -> bool:
    """Return whether a browser opened by this process would be unable to reach its loopback listener.

    Over SSH a browser either cannot start or starts on another machine (X forwarding), where 127.0.0.1 is not this
    host. On Linux without a display server there is no browser to start at all.

    Args:
        environ: Environment variables of this process.
        platform: Value of :py:data:`sys.platform`.
    """
    if environ.get("SSH_CONNECTION") or environ.get("SSH_TTY"):
        return True
    if platform.startswith("linux"):
        return not (environ.get("DISPLAY") or environ.get("WAYLAND_DISPLAY"))
    return False


def run_login(
    api: CredentialRequestApi,
    api_endpoint: str,
    options: LoginOptions,
    open_browser: typing.Callable[[str], bool],
    read_pasted_code: typing.Callable[[], str],
    out: TextOutput,
) -> IssuedToken:
    """Sign in through the browser and return the minted personal access token, to be saved or deleted.

    1. Create a credential request with a challenge derived from a secret verifier kept by this process.
    2. Print the approval URL and confirmation code. With ``options.use_loopback``, open the URL and wait for the
       browser's redirect to a listener on 127.0.0.1; otherwise read the authorization code the user pastes.
    3. Redeem the authorization code with the verifier. The token never passes through the browser.

    Use the returned token as a context manager, and save it inside the ``with`` block before reporting login success:
    a token not saved by the end of the block is deleted.

    Args:
        api: Client for the credential request endpoints.
        api_endpoint: Roboto API endpoint the token is used at: it is saved with the token, and an unsaved token is
            deleted there.
        options: How to run the flow.
        open_browser: Opens a URL in a browser; returns False if it could not.
        read_pasted_code: Reads an authorization code pasted by the user, without echoing it.
        out: Where to print instructions for the user.

    Raises:
        LoopbackListenerError: The listener for the browser's redirect could not start.
        LoginDeniedError: The request was denied in the browser.
        LoginExpiredError: The request expired before the browser approved or denied it.
        NoAuthorizationCodeError: The pasted code was empty.
        CredentialRequestRateLimitedError: Too many sign-in requests came from this network.
        CredentialRequestHttpError: Roboto refused to create the request or to exchange its authorization code.
        CredentialRequestNoResponseError: Roboto could not be reached, or its response was lost.
        LoginError: The approval URL was unsafe, or the exchange response lacked a token secret.
    """
    pkce = PkcePair.generate()

    if not options.use_loopback:
        creation_result = api.create_request(_create_request_input(options, pkce, redirect_uri=None, state=None))
        _check_sign_in_url(creation_result.approval_url)
        _print_instructions(out, creation_result, pasting=True)
        authorization_code = read_pasted_code().strip()
        if not authorization_code:
            raise NoAuthorizationCodeError("You didn't enter an authorization code.")
        return _exchange(api, api_endpoint, creation_result, authorization_code, pkce)

    state = generate_state()
    try:
        server = LoopbackCallbackServer(expected_state=state, port=options.loopback_port)
    except OSError as exc:
        port = f"port {options.loopback_port}" if options.loopback_port else "a port"
        raise LoopbackListenerError(
            f"The browser can't send the authorization code to this computer because opening {port} failed "
            + f"({exc.strerror})."
        ) from None

    with server:
        creation_result = api.create_request(
            _create_request_input(options, pkce, redirect_uri=server.redirect_uri, state=state)
        )
        _check_sign_in_url(creation_result.approval_url)
        _print_instructions(out, creation_result, pasting=False)
        if not open_browser(creation_result.approval_url):
            print("Couldn't open a browser. Open the URL above on this computer.", file=out)

        try:
            result = server.wait_for_result(timeout=_seconds_until_expiry(creation_result))
        except LoginTimeoutError:
            raise LoginExpiredError(
                "The sign-in expired before the browser sent an approval or denial to this computer."
            ) from None

    if result.error or not result.code:
        raise LoginDeniedError("You denied the sign-in in the browser.")
    return _exchange(api, api_endpoint, creation_result, result.code, pkce)


def _create_request_input(
    options: LoginOptions,
    pkce: PkcePair,
    redirect_uri: typing.Optional[str],
    state: typing.Optional[str],
) -> CreateCredentialRequest:
    return CreateCredentialRequest(
        code_challenge=pkce.challenge,
        code_challenge_method="S256",
        redirect_uri=redirect_uri,
        state=state,
        client_hostname=options.client_hostname,
        client_version=options.client_version,
        token_expiry_days=options.expiry_days,
    )


def _check_sign_in_url(url: str) -> None:
    """Refuse a URL from Roboto that isn't HTTPS: an approval URL to open or print, or an endpoint to sign in at.

    Plain HTTP is accepted only to this machine, for a local development stack.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme == "https" and parsed.hostname:
        return
    if parsed.scheme == "http" and parsed.hostname in _LOCAL_DEVELOPMENT_HOSTS:
        return
    raise LoginError(f"Roboto returned a sign-in URL that isn't HTTPS, so the CLI won't use it: {url}")


def _print_instructions(out: TextOutput, creation_result: CreateCredentialRequestResult, pasting: bool) -> None:
    print("Open this URL in a browser to sign in to Roboto:", file=out)
    print(f"\n    {creation_result.approval_url}\n", file=out)
    print(f"Check that the page shows this confirmation code: {creation_result.confirmation_code}", file=out)
    if pasting:
        print("After you approve, copy the authorization code from the page and paste it here.", file=out)
    else:
        print("Waiting for approval in the browser...", file=out)
    out.flush()


def _seconds_until_expiry(creation_result: CreateCredentialRequestResult) -> float:
    remaining = creation_result.expires - datetime.datetime.now(datetime.timezone.utc)
    return max(remaining.total_seconds(), 0.0)


def _exchange(
    api: CredentialRequestApi,
    api_endpoint: str,
    creation_result: CreateCredentialRequestResult,
    authorization_code: str,
    pkce: PkcePair,
) -> IssuedToken:
    token = api.exchange_code(
        ExchangeCredentialRequestCode(
            credential_request_id=creation_result.credential_request_id,
            authorization_code=authorization_code,
            code_verifier=pkce.verifier,
        )
    )
    if not token.secret:
        raise LoginError("Roboto didn't return an access token.")
    return IssuedToken(token, api_endpoint)
