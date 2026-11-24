# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from roboto import RobotoClient

from ...compat import StrEnum


class WebhookProvider(StrEnum):
    """Webhook provider of a webhook integration: the third-party service that sends the integration its events."""

    Foxglove = "foxglove"
    """Foxglove, which can notify Roboto when it imports a recording or when someone creates an event in Foxglove."""


class BeginWebhookIntegrationRequest(pydantic.BaseModel):
    """Request body for ``WebhookIntegrationService.begin_webhook_integration``.

    Starts a webhook integration between an organization and a webhook provider.
    """

    org_id: str
    """ID of the organization to create the integration in."""

    user_config: dict[str, typing.Any] | None = None
    """Provider-specific settings for the integration. ``None`` sets none."""

    webhook_events: list[str]
    """Provider event types the integration accepts, such as ``recording.imported``. Must not be empty."""

    webhook_provider: WebhookProvider
    """Service that sends events to the integration."""


class UpdateWebhookIntegrationSecretRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/integrations/webhook/id/{webhook_endpoint_id}/signature_secret``.

    Registers or replaces the secret Roboto checks each incoming event's signature against.
    """

    webhook_secret: pydantic.SecretStr
    """Secret the webhook provider signs its events with."""

    @pydantic.field_serializer("webhook_secret", when_used="json")
    def serialize_over_the_wire(self, value: pydantic.SecretStr) -> str:
        """Serialize ``webhook_secret`` as its plain string value in JSON, so the request body carries it.

        Pydantic calls this when it serializes the request to JSON. Other dumps and the request's ``repr`` keep the
        secret masked.
        """
        return value.get_secret_value()


class UpdateWebhookIntegrationAPIKeyRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/integrations/webhook/id/{webhook_endpoint_id}/api_key``.

    Registers or replaces the API key Roboto uses to fetch data, such as recordings, from the webhook provider.
    """

    webhook_provider_api_key: pydantic.SecretStr
    """API key for the webhook provider's API."""

    @pydantic.field_serializer("webhook_provider_api_key", when_used="json")
    def serialize_over_the_wire(self, value: pydantic.SecretStr) -> str:
        """Serialize ``webhook_provider_api_key`` as its plain string value in JSON, so the request body carries it.

        Pydantic calls this when it serializes the request to JSON. Other dumps and the request's ``repr`` keep the
        key masked.
        """
        return value.get_secret_value()


class WebhookIntegrationRecord(pydantic.BaseModel):
    """Data record of a webhook integration, as the Roboto API returns it.

    A webhook integration is an endpoint at which a third-party service, the webhook provider, sends events to an
    organization in Roboto. The record never contains the integration's secret or API key; it says only whether each
    is registered. Returned by ``WebhookIntegrationService.begin_webhook_integration``.
    """

    webhook_endpoint_id: str
    """Unique ID of the webhook integration, beginning with ``wh_``."""

    created: datetime.datetime
    """Time the integration was created."""

    created_by: str
    """ID of the user who created the integration."""

    modified: datetime.datetime
    """Time the integration was last modified."""

    modified_by: str
    """ID of the user who last modified the integration."""

    org_id: str
    """ID of the organization that owns the integration."""

    status: str
    """Status of the integration: ``in_progress`` until its secret and API key are both registered, then ``healthy``.

    Roboto rejects events sent to an integration that is ``in_progress``.
    """

    user_config: dict[str, typing.Any] | None = None
    """Provider-specific settings for the integration, or ``None`` if none were set."""

    webhook_endpoint_url: str
    """URL to configure in the webhook provider, to which it sends events."""

    webhook_events: list[str]
    """Provider event types the integration accepts, such as ``recording.imported``.

    Roboto rejects events of any other type, except the provider's ``ping`` test events.
    """

    webhook_provider: WebhookProvider
    """Service that sends events to the integration."""

    secret_registered: bool
    """Whether the secret Roboto checks event signatures against is registered."""

    api_key_registered: bool
    """Whether the API key Roboto uses to fetch data from the webhook provider is registered."""


class WebhookIntegrationService:
    """Client that starts webhook integrations, which let a webhook provider such as Foxglove send events to Roboto.

    Args:
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
    """

    __roboto_client: RobotoClient

    def __init__(self, roboto_client: typing.Optional[RobotoClient] = None):
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def begin_webhook_integration(
        self,
        org_id: str,
        webhook_provider: WebhookProvider,
        webhook_events: list[str],
        user_config: dict[str, typing.Any] | None = None,
    ) -> WebhookIntegrationRecord:
        """Create a webhook integration for an organization, with the status ``in_progress``.

        Configure the returned record's ``webhook_endpoint_url`` in the webhook provider, then register the provider's
        signing secret and API key with Roboto. The integration becomes ``healthy``, and accepts events, once both
        are registered.

        Args:
            org_id: ID of the organization to create the integration in.
            webhook_provider: Service that will send events to the integration.
            webhook_events: Provider event types the integration accepts, such as ``recording.imported``.
            user_config: Provider-specific settings for the integration. ``None`` sets none.

        Returns:
            Record of the new integration.

        Raises:
            RobotoInvalidRequestException: ``webhook_events`` is empty, or no organization has the ID ``org_id``.
            RobotoConflictException: The provider is Foxglove and the organization already has a Foxglove
                integration.

        Examples:
            >>> from roboto.domain.orgs.webhook_integration import WebhookIntegrationService, WebhookProvider
            >>> service = WebhookIntegrationService()
            >>> record = service.begin_webhook_integration(
            ...     org_id="og_12345",
            ...     webhook_provider=WebhookProvider.Foxglove,
            ...     webhook_events=["recording.imported"],
            ... )
            >>> print(record.webhook_endpoint_url)
        """
        return self.__roboto_client.post(
            path="v1/integrations/webhook/begin",
            data=BeginWebhookIntegrationRequest(
                org_id=org_id,
                user_config=user_config,
                webhook_provider=webhook_provider,
                webhook_events=webhook_events,
            ),
        ).to_record(WebhookIntegrationRecord)
