# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

RESOURCE_OWNER_OVERRIDE_HEADER = "X-Roboto-Resource-Owner-Id"
"""Header to specify the organization that owns the resource being accessed."""

RESOURCE_OWNER_OVERRIDE_QUERY_PARAM = "robotoResourceOwnerId"
"""Query parameter to specify the organization that owns the resource being accessed."""

ORG_OVERRIDE_HEADER = "X-Roboto-Org-Id"
"""Header to specify the organization that the user is acting on behalf of."""

ORG_OVERRIDE_QUERY_PARAM = "robotoOrgId"
"""Query parameter to specify the organization that the user is acting on behalf of."""

USER_OVERRIDE_HEADER = "X-Roboto-User-Id"
"""Header to specify the user that is performing the REST operation."""

USER_OVERRIDE_QUERY_PARAM = "robotoUserId"
""""Query parameter to specify the user that is performing the REST operation."""

BEARER_TOKEN_HEADER = "X-Roboto-Bearer-Token"
"""Bearer token which is parsed as a JWT to provide additional request context for invocations"""

API_VERSION_HEADER = "X-Roboto-Api-Version"
"""Which expected rolling API version this request is being made against. If no value is provided, requests will
be made against the latest API version."""

CONNECTION_CONSISTENCY_HEADER = "X-Roboto-Connection-Consistency"
"""Header to control database read consistency for query/search endpoints.

Set to 'strongly_consistent' to force strongly consistent reads,
or 'eventually_consistent' to force eventually consistent reads. Omission defaults to the API version's default.

Only applies to query and search endpoints (e.g., /v1/query/*, /v1/datasets/query,
/v1/files/query). Has no effect on other endpoints.

For API versions >= 2026-03-13, query endpoints default to eventually consistent reads.
For older API versions, they default to strongly consistent reads for backward compatibility.
"""
