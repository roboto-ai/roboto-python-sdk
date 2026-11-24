# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Clients and types for sending requests to Roboto over HTTP.

Use :py:class:`~roboto.http.RobotoClient` to send requests to a chosen Roboto endpoint with a chosen access token or
config profile. SDK methods that take a ``roboto_client`` default to the one client
:py:meth:`~roboto.http.RobotoClient.from_env` builds from the environment and reuses for every call.
"""

from .constants import (
    BEARER_TOKEN_HEADER,
    CONNECTION_CONSISTENCY_HEADER,
    ORG_OVERRIDE_HEADER,
    ORG_OVERRIDE_QUERY_PARAM,
    RESOURCE_OWNER_OVERRIDE_HEADER,
    RESOURCE_OWNER_OVERRIDE_QUERY_PARAM,
    USER_OVERRIDE_HEADER,
    USER_OVERRIDE_QUERY_PARAM,
)
from .headers import (
    CONTENT_TYPE_JSON_HEADER,
    roboto_headers,
)
from .http_client import (
    ClientError,
    HttpClient,
    HttpError,
    ServerError,
    is_expected_to_be_transient,
)
from .options import (
    HttpClientOptions,
    HttpLoggingOptions,
    HttpRetryOptions,
    RetryPredicate,
    never_retry,
)
from .request import BatchRequest, HttpRequest
from .request_decorators import (
    BearerTokenDecorator,
    SigV4AuthDecorator,
)
from .requester import (
    ROBOTO_REQUESTER_HEADER,
    RobotoRequester,
    RobotoTool,
)
from .response import (
    BatchResponse,
    BatchResponseElement,
    InvalidPaginationTokenError,
    PaginatedList,
    PaginationToken,
    PaginationTokenEncoding,
    PaginationTokenScheme,
    StreamedList,
)
from .roboto_client import DEFAULT_HTTP_TIMEOUT, RobotoClient

__all__ = (
    "BEARER_TOKEN_HEADER",
    "BatchRequest",
    "BatchResponse",
    "BatchResponseElement",
    "BearerTokenDecorator",
    "CONTENT_TYPE_JSON_HEADER",
    "CONNECTION_CONSISTENCY_HEADER",
    "ClientError",
    "DEFAULT_HTTP_TIMEOUT",
    "HttpClient",
    "HttpClientOptions",
    "HttpError",
    "HttpLoggingOptions",
    "HttpRequest",
    "HttpRetryOptions",
    "InvalidPaginationTokenError",
    "ORG_OVERRIDE_HEADER",
    "ORG_OVERRIDE_QUERY_PARAM",
    "PaginatedList",
    "PaginationToken",
    "PaginationTokenEncoding",
    "PaginationTokenScheme",
    "RESOURCE_OWNER_OVERRIDE_HEADER",
    "RESOURCE_OWNER_OVERRIDE_QUERY_PARAM",
    "ROBOTO_REQUESTER_HEADER",
    "RetryPredicate",
    "ServerError",
    "is_expected_to_be_transient",
    "never_retry",
    "SigV4AuthDecorator",
    "StreamedList",
    "USER_OVERRIDE_HEADER",
    "USER_OVERRIDE_QUERY_PARAM",
    "roboto_headers",
    "RobotoClient",
    "RobotoRequester",
    "RobotoTool",
)
