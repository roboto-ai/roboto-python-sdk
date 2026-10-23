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
"""Longest token lifetime, in days, that a :py:class:`CreateCredentialRequest` may ask for.

It matches the longest lifetime the Roboto web app offers for a new access token.
"""


class CreateTokenRequest(pydantic.BaseModel):
    """Request payload to create a new token"""

    api_scopes: typing.Optional[set[ApiScope]] = pydantic.Field(
        default=None, description="Optional set of API scopes to grant this token."
    )
    description: typing.Optional[str] = pydantic.Field(
        default=None, description="An optional longer description for this token."
    )
    expiry_days: int = pydantic.Field(description="Number of days until the token expires")
    name: str = pydantic.Field(description="A human-readable name for this token.")


class CreateCredentialRequest(pydantic.BaseModel):
    """Request payload to create a credential request.

    The CLI redeems the request for a personal access token after a user approves it in the browser.
    """

    code_challenge: str
    """Unpadded base64url encoding of the SHA-256 digest of the CLI's secret code verifier."""

    code_challenge_method: typing.Literal["S256"] = "S256"
    """Challenge method. Only S256 is supported."""

    redirect_uri: typing.Optional[str] = None
    """Loopback URL (``http://127.0.0.1:<port>/callback`` or ``http://[::1]:<port>/callback``) the browser is sent to
    after approval. The port must be 1-65535; credentials, query strings, and fragments are refused.

    When omitted, the web app shows the authorization code for the user to paste into the CLI instead, which is how
    login works on a machine without a browser.
    """

    state: typing.Optional[str] = None
    """Random value of 16 to 256 URL-safe characters, echoed back on the loopback redirect so the CLI can reject
    callbacks it did not ask for. Required with ``redirect_uri`` and rejected without it."""

    client_hostname: str
    """Hostname shown on the approval page: 1-255 printable ASCII characters, declared by the client."""

    client_version: str
    """CLI version shown on the approval page: 1-64 printable ASCII characters, declared by the client."""

    token_expiry_days: int
    """Number of days, from 1 to :py:data:`MAX_CREDENTIAL_REQUEST_TOKEN_EXPIRY_DAYS`, that the personal access token
    stays valid.

    The lifetime starts when the CLI redeems the approved request.
    """


class ExchangeCredentialRequestCode(pydantic.BaseModel):
    """Redeem an approved request's authorization code for a personal access token.

    Credential values are serialized for exchange, but hidden from model representations and rendered validation
    errors. Structured validation errors include input by default; use ``errors(include_input=False)`` when logging
    them.
    """

    model_config = pydantic.ConfigDict(hide_input_in_errors=True)

    credential_request_id: str
    """ID of the request the code was issued for."""

    authorization_code: str = pydantic.Field(repr=False)
    """One-time authorization code delivered to the CLI by the loopback redirect or pasted by the user."""

    code_verifier: str = pydantic.Field(repr=False)
    """Secret verifier whose SHA-256 digest, encoded as unpadded base64url, was sent as ``code_challenge``."""


class CreateCredentialRequestResult(pydantic.BaseModel):
    """Creation result for a credential request that expires ten minutes after creation."""

    credential_request_id: str
    """Unique identifier for the request. Redeeming it also requires its authorization code and secret verifier."""

    confirmation_code: str
    """Short code the CLI prints and the approval page shows, so the user can check they are the same request."""

    approval_url: str
    """Web app URL where the user reviews and approves the request."""

    expires: datetime.datetime
    """Time after which the request can no longer be approved or redeemed."""
