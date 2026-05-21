# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...sentinels import NotSet, NotSetType
from ...updates import CustomFieldChangeset, MetadataChangeset


class CreateSessionRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/sessions``.

    Creates a new session with zero, one, or many devices attached as subjects.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    name: typing.Optional[str] = pydantic.Field(default=None, max_length=120)
    device_ids: list[str] = pydantic.Field(default_factory=list)

    description: typing.Optional[str] = None
    """Optional description of the Session."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata to associate with the Session.

    Sessions cannot be filtered or sorted by ``metadata`` keys;
    for queryable structured attributes, define a custom field on the ``Session`` entity type.
    """

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to associate with the Session."""

    custom_fields: typing.Optional[dict[str, typing.Any]] = None
    """Initial values for Ready custom fields on this session.

    Each key must be the name of a :py:class:`~roboto.domain.custom_fields.CustomField`
    that is :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` for the
    caller's org and the :py:class:`~roboto.domain.custom_fields.TargetEntityType.Session`
    entity type; each value must satisfy the field's declared type. Names that are
    undefined or not ``Ready``, and values that don't match the field's type, are
    rejected with a structured error.
    """


class SessionUpdate(pydantic.BaseModel):
    """Partial update for a session.

    Fields left at ``NotSet`` are not modified.
    """

    model_config = pydantic.ConfigDict(
        extra="ignore",
        json_schema_extra=NotSetType.openapi_schema_modifier,
    )

    description: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """New description for the Session. Set to ``None`` to clear the description."""

    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    """Tag and metadata changes to merge into the Session (add, update, or remove fields and tags)."""

    name: typing.Optional[
        typing.Union[typing.Annotated[str, pydantic.StringConstraints(max_length=120)], NotSetType]
    ] = NotSet
    """New name for the Session (max 120 characters). Set to ``None`` to clear the name."""

    custom_fields_changeset: typing.Optional[CustomFieldChangeset] = None
    """Changes to apply to Ready custom-field values on this session.

    Each referenced field name must be a
    :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` custom field
    for this session's org and the
    :py:class:`~roboto.domain.custom_fields.TargetEntityType.Session` entity type;
    each ``set_fields`` value must satisfy the field's declared type. Names that
    are undefined or not ``Ready`` are rejected with a structured error. Field
    names not mentioned by the changeset are left unchanged.
    """


class AttachToDeviceRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/sessions/id/<session_id>/devices``.

    Attaches a device as a subject of the session.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    device_id: str


class SessionFile(pydantic.BaseModel):
    """A file's contribution to a session, optionally narrowed to a time range.

    ``range_min_timestamp_ns`` and ``range_max_timestamp_ns`` are absolute nanoseconds since the Unix epoch,
    the same coordinate system in which the session's aggregate bounds are expressed.
    Leaving both bounds as ``None`` contributes the whole file's time window.
    Both bounds must be set together or both omitted; half-open windows are rejected.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    file_id: str
    range_min_timestamp_ns: typing.Optional[int] = None
    range_max_timestamp_ns: typing.Optional[int] = None

    @pydantic.model_validator(mode="after")
    def _check_range(self) -> "SessionFile":
        if (self.range_min_timestamp_ns is None) != (self.range_max_timestamp_ns is None):
            raise ValueError("range_min_timestamp_ns and range_max_timestamp_ns must be set together or both omitted")
        if (
            self.range_min_timestamp_ns is not None
            and self.range_max_timestamp_ns is not None
            and self.range_min_timestamp_ns > self.range_max_timestamp_ns
        ):
            raise ValueError("range_min_timestamp_ns must be <= range_max_timestamp_ns")
        return self


class AddFilesRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/sessions/id/<session_id>/files``.

    Adds one or more files as contributions to the session.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    files: list[SessionFile]


class DetachFromDeviceRequest(pydantic.BaseModel):
    """Request body for ``DELETE /v1/sessions/id/<session_id>/devices``.

    Detaches a device from the session; the session itself is not deleted.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    device_id: str


class RemoveFilesRequest(pydantic.BaseModel):
    """Request body for ``DELETE /v1/sessions/id/<session_id>/files``.

    Removes the listed files' contributions from the session.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    file_ids: list[str]
