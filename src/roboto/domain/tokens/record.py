# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
from typing import Optional

import pydantic

from roboto.auth.scope import ApiScope


class TokenContext(pydantic.BaseModel):
    """Details of a personal access token other than its secret and owner: its name, lifetime, scopes, and state.

    Carried in ``TokenRecord.context``.
    """

    token_id: str
    """Unique ID of the token, beginning with ``to_``."""

    name: str
    """Human-readable name of the token."""

    description: Optional[str] = None
    """Human-readable description of the token, or ``None`` if it has none."""

    expires: datetime.datetime
    """Time the token expires, after which it no longer authenticates requests."""

    last_used: Optional[datetime.datetime] = None
    """Time the token last authenticated a request, or ``None`` if it never has.

    Roboto records a use only when the recorded time is at least an hour old, so this can be up to an hour behind the
    token's latest use.
    """

    api_scopes: set[ApiScope]
    """API scopes the token holds, which limit the requests it can authenticate.

    A token created without scopes holds every scope.
    """

    enabled: bool = True
    """Whether the token can authenticate requests. Roboto rejects a request made with a disabled token."""


class TokenRecord(pydantic.BaseModel):
    """Data record of a personal access token, as the Roboto API returns it.

    A personal access token authenticates requests to Roboto as the user who owns it.
    :py:class:`~roboto.domain.tokens.Token` wraps this record with methods that act on the token, and exposes it as
    :py:attr:`~roboto.domain.tokens.Token.record`.
    """

    secret: Optional[str] = None
    """Secret value that authenticates requests, or ``None`` in every response except the one that creates the token.

    Roboto does not store the secret, so it returns it once: from :py:meth:`~roboto.domain.tokens.Token.create` or
    :py:meth:`~roboto.domain.devices.Device.create_token`. A lost secret cannot be recovered; delete the token and
    create another.
    """

    user_id: Optional[str] = None
    """ID of the user who owns the token, which for a person is their email address."""

    context: Optional[TokenContext] = None
    """Details of the token other than its secret and owner."""
