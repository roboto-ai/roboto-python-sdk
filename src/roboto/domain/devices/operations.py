# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing
import unicodedata

import pydantic
import pydantic_core

from ...sentinels import NotSet, NotSetType
from ...updates import CustomFieldChangeset, MetadataChangeset

INVALID_DEVICE_ID_MESSAGE = (
    "A device ID must not be empty, `.` or `..`, and must not contain control characters or any of "
    + "`:` `@` `/` `?` `#` `%`."
)
"""Error message for a device ID that ``validate_device_id`` refuses."""


def validate_device_id(device_id: str) -> str:
    """Reject a device ID that a new device may not have.

    A device ID must not be empty, ``.`` or ``..``, and must not contain a control character (such as a tab or a
    newline) or any of ``:``, ``@``, ``/``, ``?``, ``#`` and ``%``. Any other ID is allowed, including one with
    spaces, other punctuation or non-ASCII letters.

    Args:
        device_id: Device ID to check.

    Returns:
        ``device_id``, unchanged.

    Raises:
        pydantic_core.PydanticCustomError: ``device_id`` is not allowed. Its message is ``INVALID_DEVICE_ID_MESSAGE``.
    """
    # What each refused ID or character breaks:
    # - ":" is refused by RobotoPrincipal. A request made with the device's token builds the principal
    #   "<device_id>@<org_id>" whenever it records who made a change, so every such request fails.
    # - "@" makes the Roboto web app, which splits a device principal on "@", link "created by" to the wrong device.
    # - "/", "?" and "#" give a roboto://device/<id> link a second path segment, a query or a fragment.
    # - "%": the web app percent-decodes the ID in a roboto:// link, and Roboto's AI writes the ID into such links
    #   without encoding it, so a "%" makes the decoding throw or yield a different ID.
    # - Roboto cannot store "\0" in an ID, and URL parsers drop tabs and newlines from links.
    # - "." and ".." are dot segments, so the browser resolves the device page's URL to another page.
    if device_id in ("", ".", "..") or any(
        character in ":@/?#%" or unicodedata.category(character) == "Cc" for character in device_id
    ):
        raise pydantic_core.PydanticCustomError("device_id_not_allowed", INVALID_DEVICE_ID_MESSAGE)
    return device_id


class CreateDeviceRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.devices.Device.create`.

    Building one with a ``device_id`` that ``validate_device_id`` refuses raises ``pydantic.ValidationError``.
    """

    device_id: str
    """ID of the device, chosen by the caller and unique within the device's organization.

    ``validate_device_id`` lists the IDs Roboto refuses.
    """

    org_id: typing.Optional[str] = None
    """Organization to create the device in.

    Roboto ignores it and uses the organization the request acts in instead.
    :py:meth:`~roboto.domain.devices.Device.create` sets both from its ``caller_org_id``, so they agree.
    """

    metadata: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        description="Initial key-value pairs to associate with this device for discovery and search, e.g. "
        + "`{ 'model': 'mk2', 'serial_number': 'SN001234' }`",
    )
    """Key-value metadata to set on the device."""

    tags: list[str] = pydantic.Field(
        default_factory=list,
        description="Initial tags to associate with this device for discovery and search, e.g. "
        + "`['production', 'warehouse-a']`",
    )
    """Tags to set on the device. Defaults to none."""

    custom_fields: typing.Optional[dict[str, typing.Any]] = None
    """Initial values for the device's custom fields, keyed by field name. ``None`` sets none.

    Each name must be a :py:class:`~roboto.domain.custom_fields.CustomField` defined for
    :py:attr:`~roboto.domain.custom_fields.TargetEntityType.Device` in the organization the device is created in,
    with status :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
    field's declared type. Otherwise the request fails with
    :py:class:`~roboto.exceptions.RobotoIllegalArgumentException`.
    """

    device_type_id: typing.Optional[str] = None
    """ID of the device type to assign to the device, beginning with ``dt_``. ``None`` leaves the device without one.

    The device type must be in the organization the device is created in; any other raises
    ``RobotoInvalidRequestException``.
    """

    @pydantic.field_validator("device_id")
    @classmethod
    def _validate_device_id(cls, value: str) -> str:
        return validate_device_id(value)


class UpdateDeviceRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.devices.Device.update`.

    A field left at its default (``NotSet`` or ``None``) is unchanged.
    """

    metadata_changeset: typing.Optional[MetadataChangeset] = None
    """Changes to the device's tags and metadata."""

    custom_fields_changeset: typing.Optional[CustomFieldChangeset] = None
    """Changes to the device's custom-field values.

    Each field name the changeset references must be a custom field defined for
    :py:attr:`~roboto.domain.custom_fields.TargetEntityType.Device` in the device's organization, with status
    :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each ``set_fields`` value must match that
    field's declared type. Otherwise the request fails with
    :py:class:`~roboto.exceptions.RobotoIllegalArgumentException`. See
    :py:class:`~roboto.updates.CustomFieldChangeset`.
    """

    device_type_id: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """ID of the device type to assign to the device, beginning with ``dt_``. ``None`` removes the device's type.

    The device type must be in the device's organization; any other raises ``RobotoInvalidRequestException``.
    """

    model_config = pydantic.ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)


class InferDevicesRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/devices/infer``.

    The response lists the devices a session created from these files would be attached to: every device set as
    ``device_id`` on one of the files or on its dataset. The request creates and changes nothing.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    file_ids: list[str]
    """IDs of the files to infer devices from. A file outside the request's organization adds no devices."""


class InferDevicesResponse(pydantic.BaseModel):
    """Response body of ``POST /v1/devices/infer``."""

    model_config = pydantic.ConfigDict(extra="ignore")

    device_ids: list[str]
    """IDs of the inferred devices, each listed once, in no particular order."""
