# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

SERVICE_DISCOVERY_PATH = "/.well-known/roboto.json"
"""Path of a deployment's service discovery document, relative to its Roboto API endpoint.

``ServiceDiscoveryDocument`` describes the document.
"""


class ServiceDiscoveryDocument(pydantic.BaseModel):
    """Response body of ``GET /.well-known/roboto.json``: the services a Roboto deployment offers, and their base URLs.

    The Roboto API serves it without requiring credentials, as a JSON object that maps a versioned service name, such
    as ``credential_requests.v1``, to the base URL serving that version of the service. A service the deployment does
    not offer is absent from the object. Names this model does not know are ignored, so a deployment can offer new
    services, or new versions of a service, without breaking older clients.
    """

    credential_requests_v1: typing.Optional[str] = pydantic.Field(default=None, alias="credential_requests.v1")
    """Base URL of the credential request service, or ``None`` if the deployment does not offer browser sign-in.

    ``roboto auth login`` and ``roboto setup`` create a credential request there (``POST /v1/tokens/requests``) and
    redeem its authorization code (``POST /v1/tokens/requests/exchange``). The URL, such as
    ``https://api-public.roboto.ai``, can differ from the Roboto API endpoint the issued token is used at."""
