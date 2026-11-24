# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Personal access tokens: credentials that authenticate requests to Roboto as the user who owns them.

Use :py:class:`~roboto.domain.tokens.Token` to create, list, disable, and delete personal access tokens.
"""

from .operations import (
    MAX_CREDENTIAL_REQUEST_TOKEN_EXPIRY_DAYS,
    CreateCredentialRequest,
    CreateCredentialRequestResult,
    CreateTokenRequest,
    ExchangeCredentialRequestCode,
)
from .record import TokenContext, TokenRecord
from .token import Token

__all__ = [
    "MAX_CREDENTIAL_REQUEST_TOKEN_EXPIRY_DAYS",
    "CreateCredentialRequest",
    "CreateCredentialRequestResult",
    "ExchangeCredentialRequestCode",
    "CreateTokenRequest",
    "Token",
    "TokenRecord",
    "TokenContext",
]
