# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

SERVICE_DISCOVERY_PATH = "/.well-known/roboto.json"
"""Path, relative to a Roboto API endpoint, at which the deployment serves its :py:class:`ServiceDiscoveryDocument`."""


class ServiceDiscoveryDocument(pydantic.BaseModel):
    """The services a Roboto deployment offers, and the base URL of each.

    The deployment's Roboto API serves it at :py:data:`SERVICE_DISCOVERY_PATH` without requiring credentials, as a JSON
    object that maps a versioned service name, such as ``credential_requests.v1``, to the base URL serving that version
    of the service. A service the deployment doesn't offer is absent from the object. Names this model doesn't know are
    ignored, so a deployment can offer new services, or new versions of a service, without breaking older clients.
    """

    credential_requests_v1: typing.Optional[str] = pydantic.Field(default=None, alias="credential_requests.v1")
    """Base URL at which ``roboto auth login`` and ``roboto setup`` create a credential request
    (``POST v1/tokens/requests``) and redeem its authorization code (``POST v1/tokens/requests/exchange``), such as
    ``https://api-public.roboto.ai``. It can differ from the Roboto API endpoint the issued token is used at. None if
    the deployment doesn't offer browser sign-in."""
