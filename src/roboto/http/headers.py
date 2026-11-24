# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional

from ..api_version import RobotoApiVersion
from .constants import (
    API_VERSION_HEADER,
    ORG_OVERRIDE_HEADER,
    RESOURCE_OWNER_OVERRIDE_HEADER,
    USER_OVERRIDE_HEADER,
)

CONTENT_TYPE_JSON_HEADER = {"Content-Type": "application/json"}
"""Header naming JSON as the request body's content type, as a dictionary to merge into a request's headers.

No SDK method reads it.
"""


def roboto_headers(
    org_id: Optional[str] = None,
    user_id: Optional[str] = None,
    resource_owner_id: Optional[str] = None,
    additional_headers: Optional[dict[str, str]] = None,
    api_version: RobotoApiVersion = RobotoApiVersion.latest(),
):
    """Build the headers that tell Roboto which API version, organization and user a request is for.

    :py:meth:`~roboto.http.RobotoClient.get` and the other request methods of :py:class:`~roboto.http.RobotoClient`
    build their headers through it, so most code never calls it. The result always names the API version; each other
    argument adds its header only when it is not ``None``.

    Args:
        org_id: Organization to act in, sent as :py:const:`~roboto.http.ORG_OVERRIDE_HEADER`. Required when the
            caller belongs to more than one organization; otherwise the caller's only organization.
        user_id: ID of the user to act as, which for a person is their email address, sent as
            :py:const:`~roboto.http.USER_OVERRIDE_HEADER`. ``None`` acts as the caller.
        resource_owner_id: Organization that owns the resource the request reads or changes, sent as
            :py:const:`~roboto.http.RESOURCE_OWNER_OVERRIDE_HEADER`. ``None`` omits the header.
        additional_headers: Further headers to send. They are added last, so one with the same name as a header above
            replaces it.
        api_version: API version the request is made against. Defaults to the newest version this SDK knows.

    Returns:
        Header names mapped to their values.
    """
    headers: dict[str, str] = {API_VERSION_HEADER: api_version}

    if org_id is not None:
        headers[ORG_OVERRIDE_HEADER] = org_id

    if user_id is not None:
        headers[USER_OVERRIDE_HEADER] = user_id

    if resource_owner_id is not None:
        headers[RESOURCE_OWNER_OVERRIDE_HEADER] = resource_owner_id

    if additional_headers is not None:
        headers.update(additional_headers)

    return headers
