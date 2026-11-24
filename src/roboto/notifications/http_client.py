# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Any, Optional

from roboto.exceptions import (
    RobotoHttpExceptionParse,
)
from roboto.http import HttpClient

from .http_resources import (
    UpdateNotificationRequest,
)
from .record import NotificationChannel


class NotificationsClient:
    """Client for the caller's notifications: list them, mark them read, record their delivery, and delete them.

    Each method sends one request. Its result is Roboto's response as a JSON-compatible dictionary, not a
    :py:class:`~roboto.notifications.NotificationRecord` or other model.

    Args:
        http_client: HTTP client to send the requests with, such as the
            :py:attr:`~roboto.http.RobotoClient.http_client` of a :py:class:`~roboto.http.RobotoClient`.
    """

    __http_client: HttpClient

    def __init__(self, http_client: HttpClient):
        super().__init__()
        self.__http_client = http_client

    def get_notifications(self) -> dict[str, Any]:
        """Fetch the first page of the caller's notifications in the organization the caller acts in, newest first.

        A page holds up to 100 notifications. This method sends no page token, so it cannot fetch the pages after the
        first.

        Returns:
            :py:class:`~roboto.http.PaginatedList` of :py:class:`~roboto.notifications.NotificationRecord`, as a
            JSON-compatible dictionary. ``items`` holds the notifications.
        """
        url = self.__http_client.url("v1/notifications")

        with RobotoHttpExceptionParse():
            response = self.__http_client.get(url=url)

            return response.to_dict(json_path=["data"])

    def update_notification(
        self,
        notification_id: str,
        org_id: Optional[str] = None,
        read_status: Optional[str] = None,
        lifecycle_status: Optional[dict[NotificationChannel, str]] = None,
    ) -> Any:
        """Update a notification's read status or its delivery status on some channels.

        The caller may update only their own notifications, unless they are a Roboto administrator.

        Args:
            notification_id: ID of the notification to update.
            org_id: Organization to act in. Required when the caller belongs to more than one organization; otherwise
                the caller's only organization.
            read_status: Read status to set, a :py:class:`~roboto.notifications.ReadStatus` value such as ``"read"``.
                ``None`` leaves it unchanged.
            lifecycle_status: Delivery status to set on each channel it names, keyed by channel. Channels it does not
                name keep their status. ``None`` leaves every channel unchanged.

        Returns:
            :py:class:`~roboto.notifications.NotificationRecord` of the updated notification, as a JSON-compatible
            dictionary.

        Raises:
            RobotoNotFoundException: The organization has no notification with this ID.
            RobotoUnauthorizedException: The notification is for another user and the caller is not a Roboto
                administrator.
        """
        url = self.__http_client.url(f"v1/notifications/{notification_id}")

        body: dict[str, Any] = {
            "notification_id": notification_id,
        }

        request_headers: Optional[dict[str, str]] = None

        if org_id is not None:
            request_headers = {
                "X-Roboto-Org-Id": org_id,
            }

        if read_status is not None:
            body["read_status"] = read_status

        if lifecycle_status is not None:
            body["lifecycle_status"] = lifecycle_status

        with RobotoHttpExceptionParse():
            response = self.__http_client.put(
                url=url,
                data=body,
                headers=request_headers,
            )

            return response.to_dict(json_path=["data"])

    def batch_update_notifications(self, updates: list[UpdateNotificationRequest]) -> dict[str, Any]:
        """Update several of the caller's notifications in one request.

        Roboto applies each update on its own. An update naming a notification that does not exist or is for another
        user fails with ``RobotoNotFoundException`` in its element of the response, and the other updates still apply.

        Args:
            updates: Updates to apply, one per notification.

        Returns:
            :py:class:`~roboto.http.BatchResponse` of :py:class:`~roboto.notifications.NotificationRecord`, as a
            JSON-compatible dictionary. ``responses`` holds the outcome of each update, in the order of ``updates``.

        Raises:
            RobotoInvalidRequestException: ``updates`` is empty.
        """
        url = self.__http_client.url("v1/notifications/batch")

        dict_updates = []

        for update in updates:
            model_dict = update.model_dump()
            dict_updates.append(model_dict)

        with RobotoHttpExceptionParse():
            response = self.__http_client.put(
                url=url,
                data={
                    "requests": dict_updates,
                },
            )

            return response.to_dict(json_path=["data"])

    def delete_notification(self, notification_id: str) -> None:
        """Delete one of the caller's notifications in the organization the caller acts in.

        Args:
            notification_id: ID of the notification to delete.

        Raises:
            RobotoNotFoundException: The organization has no notification with this ID.
            RobotoUnauthorizedException: The notification is for another user.
        """
        url = self.__http_client.url(f"v1/notifications/{notification_id}")

        with RobotoHttpExceptionParse():
            self.__http_client.delete(
                url=url,
            )

            return None
