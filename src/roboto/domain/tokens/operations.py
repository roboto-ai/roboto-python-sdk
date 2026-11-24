# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from roboto.auth.scope import ApiScope

MAX_CREDENTIAL_REQUEST_TOKEN_EXPIRY_DAYS = 365
"""Maximum lifetime of the token a ``CreateCredentialRequest`` asks for, in days.

It matches the longest lifetime the Roboto web app offers for a new personal access token.
"""


class CreateTokenRequest(pydantic.BaseModel):
    """Request body to create an access token.

    Sent by :py:meth:`~roboto.domain.tokens.Token.create` and :py:meth:`~roboto.domain.devices.Device.create_token`.
    """

    api_scopes: typing.Optional[set[ApiScope]] = pydantic.Field(
        default=None, description="Optional set of API scopes to grant this token."
    )
    """API scopes the token is limited to. ``None`` or an empty set grants every scope.

    The token cannot be granted more than the credential creating it holds.
    """

    description: typing.Optional[str] = pydantic.Field(
        default=None, description="An optional longer description for this token."
    )
    """Human-readable description of the token."""

    expiry_days: int = pydantic.Field(description="Number of days until the token expires")
    """Number of days the token stays valid, counted from its creation."""

    name: str = pydantic.Field(description="A human-readable name for this token.")
    """Human-readable name of the token."""


class CreateCredentialRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/tokens/requests``.

    Sent by ``roboto auth login``. The request asks a user to approve, in the browser, a personal access token for the
    CLI. The CLI then redeems the approval with ``ExchangeCredentialRequestCode``. A field outside the limits its
    docstring gives raises ``RobotoInvalidRequestException``. Building the model raises ``pydantic.ValidationError``
    for a ``code_challenge_method`` other than ``"S256"``.
    """

    code_challenge: str
    """Unpadded base64url encoding of the SHA-256 digest of the CLI's secret verifier.

    The CLI sends the verifier itself when it redeems the approval, as ``ExchangeCredentialRequestCode.code_verifier``.
    """

    code_challenge_method: typing.Literal["S256"] = "S256"
    """Method that derives ``code_challenge`` from the verifier. Only ``"S256"`` is accepted."""

    redirect_uri: typing.Optional[str] = None
    """Loopback URL the browser is sent to after approval, or ``None`` to have the user paste the authorization code.

    Must be ``http://127.0.0.1:<port>/callback`` or ``http://[::1]:<port>/callback``, with a port from 1 to 65535 and
    no credentials, query string, or fragment. ``None`` makes the Roboto web app show the authorization code for the
    user to paste into the CLI, which is how sign-in works on a machine without a browser.
    """

    state: typing.Optional[str] = None
    """Random value echoed back on the loopback redirect, so the CLI can reject callbacks it did not ask for.

    16 to 256 letters, digits, ``-`` or ``_``. Required with ``redirect_uri`` and rejected without it.
    """

    client_hostname: str
    """Hostname the client declares, shown on the approval page: 1 to 255 printable ASCII characters."""

    client_version: str
    """CLI version the client declares, shown on the approval page: 1 to 64 printable ASCII characters."""

    token_expiry_days: int
    """Number of days the personal access token stays valid, counted from when the CLI redeems the approved request.

    From 1 to 365 (``MAX_CREDENTIAL_REQUEST_TOKEN_EXPIRY_DAYS``).
    """


class ExchangeCredentialRequestCode(pydantic.BaseModel):
    """Request body for ``POST /v1/tokens/requests/exchange``.

    Sent by ``roboto auth login``. Redeems an approved credential request's authorization code for a personal access
    token. ``authorization_code`` and ``code_verifier`` are left out of the model's ``repr`` and of a
    ``pydantic.ValidationError``'s message, but ``ValidationError.errors()`` still includes them unless called with
    ``include_input=False``.
    """

    model_config = pydantic.ConfigDict(hide_input_in_errors=True)

    credential_request_id: str
    """ID of the credential request the code was issued for."""

    authorization_code: str = pydantic.Field(repr=False)
    """One-time authorization code, delivered to the CLI by the loopback redirect or pasted by the user."""

    code_verifier: str = pydantic.Field(repr=False)
    """Secret verifier whose SHA-256 digest, encoded as unpadded base64url, was sent as ``code_challenge``."""


class CreateCredentialRequestResult(pydantic.BaseModel):
    """Response body of ``POST /v1/tokens/requests``: a credential request that expires ten minutes after creation."""

    credential_request_id: str
    """Unique ID of the credential request. Redeeming it also requires its authorization code and secret verifier."""

    confirmation_code: str
    """Short code the CLI prints and the approval page shows, so the user can check they are the same request."""

    approval_url: str
    """URL in the Roboto web app where the user reviews and approves the request."""

    expires: datetime.datetime
    """Time after which the request can no longer be approved or redeemed."""
