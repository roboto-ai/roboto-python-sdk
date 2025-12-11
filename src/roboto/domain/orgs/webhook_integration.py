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
    Foxglove = "foxglove"


class BeginWebhookIntegrationRequest(pydantic.BaseModel):
    org_id: str
    user_config: dict[str, typing.Any] | None = None
    webhook_events: list[str]
    webhook_provider: WebhookProvider


class UpdateWebhookIntegrationSecretRequest(pydantic.BaseModel):
    webhook_secret: pydantic.SecretStr

    @pydantic.field_serializer("webhook_secret", when_used="json")
    def serialize_over_the_wire(self, value: pydantic.SecretStr) -> str:
        return value.get_secret_value()


class UpdateWebhookIntegrationAPIKeyRequest(pydantic.BaseModel):
    webhook_provider_api_key: pydantic.SecretStr

    @pydantic.field_serializer("webhook_provider_api_key", when_used="json")
    def serialize_over_the_wire(self, value: pydantic.SecretStr) -> str:
        return value.get_secret_value()


class WebhookIntegrationRecord(pydantic.BaseModel):
    webhook_endpoint_id: str
    created: datetime.datetime
    created_by: str
    modified: datetime.datetime
    modified_by: str
    org_id: str
    status: str
    user_config: dict[str, typing.Any] | None = None
    webhook_endpoint_url: str
    webhook_events: list[str]
    webhook_provider: WebhookProvider
    secret_registered: bool
    api_key_registered: bool


class WebhookIntegrationService:
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
        return self.__roboto_client.post(
            path="v1/integrations/webhook/begin",
            data=BeginWebhookIntegrationRequest(
                org_id=org_id,
                user_config=user_config,
                webhook_provider=webhook_provider,
                webhook_events=webhook_events,
            ),
        ).to_record(WebhookIntegrationRecord)
