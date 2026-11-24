# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...pydantic.serializers import field_serializer_custom_field_values


class DeviceRecord(pydantic.BaseModel):
    """Data record of a device, as the Roboto API returns it.

    A device is a robot, upload station, or other non-human entity that interacts with Roboto on behalf of an
    organization. :py:class:`~roboto.domain.devices.Device` wraps this record with methods that act on the device, and
    exposes it as :py:attr:`~roboto.domain.devices.Device.record`.
    """

    created: datetime.datetime
    """Time the device was created."""

    created_by: str
    """Principal that created the device, as ``<type>:<id>``, such as ``user:<user_id>``."""

    device_id: str
    """ID the organization gave the device, such as a serial number, unique within the organization."""

    universal_device_id: typing.Optional[str] = None
    """Unique ID of the device across all organizations, beginning with ``dv_``.

    Fixed when the device is created. Roboto sets it; no request does. Pass this ID, not ``device_id``, to
    :py:meth:`~roboto.association.Association.device`.
    """

    modified: datetime.datetime
    """Time the device was last modified."""

    modified_by: str
    """Principal that last modified the device, in the same ``<type>:<id>`` form as ``created_by``."""

    org_id: str
    """ID of the organization that owns the device."""

    device_type_id: typing.Optional[str] = None
    """ID of the device type assigned to the device, beginning with ``dt_``, or ``None`` if it has none."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata on the device."""

    custom_fields: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Values of the custom fields the organization defines for devices, keyed by field name.

    Every device custom field in the :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` state appears
    as a key, mapped to ``None`` when the device has no value for it. Fields in any other state are absent, so the
    map is empty when no device custom field is in that state.
    """

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the device."""

    @pydantic.field_serializer("custom_fields", when_used="json")
    def _serialize_custom_fields(self, custom_fields: dict[str, typing.Any]) -> dict[str, typing.Any]:
        return field_serializer_custom_field_values(custom_fields)
