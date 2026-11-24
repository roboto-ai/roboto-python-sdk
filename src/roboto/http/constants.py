# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

RESOURCE_OWNER_OVERRIDE_HEADER = "X-Roboto-Resource-Owner-Id"
"""Header naming the organization that owns the resource a request reads or changes.

Without it, Roboto uses the organization the request acts in (``ORG_OVERRIDE_HEADER``).
"""

RESOURCE_OWNER_OVERRIDE_QUERY_PARAM = "robotoResourceOwnerId"
"""Query parameter that does the same as ``RESOURCE_OWNER_OVERRIDE_HEADER``, read when the header is absent.

No SDK method reads it.
"""

ORG_OVERRIDE_HEADER = "X-Roboto-Org-Id"
"""Header naming the organization a request acts in.

Required when the caller belongs to more than one organization; otherwise Roboto uses the caller's only organization.
"""

ORG_OVERRIDE_QUERY_PARAM = "robotoOrgId"
"""Query parameter that does the same as ``ORG_OVERRIDE_HEADER``, read when the header is absent.

No SDK method reads it.
"""

USER_OVERRIDE_HEADER = "X-Roboto-User-Id"
"""Header naming the user a request acts on behalf of, by user ID, which for a person is their email address.

Only Roboto's own system user may name a user other than itself; Roboto refuses the request when any other caller
does.
"""

USER_OVERRIDE_QUERY_PARAM = "robotoUserId"
"""Query parameter that does the same as ``USER_OVERRIDE_HEADER``, read when the header is absent.

No SDK method reads it.
"""

BEARER_TOKEN_HEADER = "X-Roboto-Bearer-Token"
"""Header naming a Roboto bearer token sent alongside a request's own credentials.

Roboto does not authenticate a request by this header. No SDK method reads it.
"""

API_VERSION_HEADER = "X-Roboto-Api-Version"
"""Header naming the API version a request is made against, as a date such as ``2026-03-13``.

Without it, or with a version Roboto does not recognize, the request uses the latest API version.
"""

CONNECTION_CONSISTENCY_HEADER = "X-Roboto-Connection-Consistency"
"""Header naming whether a query or listing must include the most recent changes.

``strongly_consistent`` includes every change already made. ``eventually_consistent`` can miss a change made a moment
before, so retry when a recent change is not yet visible. An endpoint that honors the header rejects any other value
with ``RobotoInvalidRequestException``.

Without the header, a request on an API version before ``2026-03-13`` reads strongly consistently, and a request on a
later version reads eventually consistently. Only some endpoints that query or list data honor the header, such as
``POST /v1/datasets/query`` and ``POST /v1/files/query``; every other endpoint ignores it. No SDK method reads it.
"""
