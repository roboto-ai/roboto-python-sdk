# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional

from .constants import (
    ORG_OVERRIDE_HEADER,
    RESOURCE_OWNER_OVERRIDE_HEADER,
    USER_OVERRIDE_HEADER,
)

CONTENT_TYPE_JSON_HEADER = {"Content-Type": "application/json"}


def roboto_headers(
    org_id: Optional[str] = None,
    user_id: Optional[str] = None,
    resource_owner_id: Optional[str] = None,
    additional_headers: Optional[dict[str, str]] = None,
):
    headers = {}

    if org_id is not None:
        headers[ORG_OVERRIDE_HEADER] = org_id

    if user_id is not None:
        headers[USER_OVERRIDE_HEADER] = user_id

    if resource_owner_id is not None:
        headers[RESOURCE_OWNER_OVERRIDE_HEADER] = resource_owner_id

    if additional_headers is not None:
        headers.update(additional_headers)

    return headers
