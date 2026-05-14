# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import datetime
import typing
import urllib.parse

from ...exceptions import (
    RobotoInvalidStateTransitionException,
    RobotoNotFoundException,
)
from ...http import RobotoClient
from ...sentinels import NotSet, NotSetType, remove_not_set
from ...waiters import wait_for
from ...warnings import experimental
from .operations import CreateCustomFieldRequest, ListCustomFieldsRequest, UpdateCustomFieldRequest
from .record import CustomFieldOptions, CustomFieldRecord, CustomFieldStatus, CustomFieldType, TargetEntityType


@experimental
class CustomField:
    """A typed, queryable schema extension defined by an organization for a Roboto entity type.

    Custom fields let an organization extend Roboto's built-in entity schemas with
    typed fields tailored to its data and workflows. Each field is scoped to one
    :py:class:`TargetEntityType` (e.g. Dataset, Collection, or Device) and is
    optimized for efficient search — equality, range, prefix, and sort — on its
    values.

    A field's :py:attr:`status` tells you what you can do with it:

    - ``Creating``: the field is being set up. Values cannot yet be assigned to
      entities, and search and sort queries cannot reference it.
    - ``Ready``: the field is available end-to-end. Values can be set on entities
      of ``entity_type``, and the field can be used in search filters and to sort
      search results.
    - ``Deleting``: the field is on its way out. Callers should treat it as already
      gone — values can no longer be set and the field will shortly disappear.
    - ``Failed``: the most recent create or delete attempt did not succeed.

    Create and delete return as soon as the status transition has been recorded;
    the rest of the work happens asynchronously. Use :py:meth:`wait_to_be_ready`
    after :py:meth:`create` and :py:meth:`wait_to_be_deleted` after :py:meth:`delete`
    if you need to wait for that work to finish.

    Field names are unique within an ``(org_id, entity_type)`` pair, must match
    ``^[a-z][a-z0-9_]{0,62}$`` (lowercase ASCII, max 63 chars), and are subject to a
    per-org-tier quota on each entity type.
    """

    __record: CustomFieldRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        field_name: str,
        field_type: CustomFieldType,
        entity_type: TargetEntityType,
        display_name: typing.Optional[str] = None,
        description: typing.Optional[str] = None,
        options: typing.Optional[CustomFieldOptions] = None,
        metadata_path: typing.Optional[str] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> CustomField:
        """Define a new custom field for an entity type in the caller's organization.

        Returns as soon as the field has been registered. The newly created field is
        typically still ``Creating`` and is not yet usable for setting values or
        running queries; call :py:meth:`wait_to_be_ready` if you need to use the
        field immediately.

        Only administrators in the organization can define new custom fields.

        Args:
            field_name: Name of the field, unique within the ``(org_id, entity_type)``
                pair. Must match ``^[a-z][a-z0-9_]{0,62}$``. Fixed at creation time
                — cannot be changed later.
            field_type: Value type of the field. Determines which operators are
                supported in search and sort.
            entity_type: Roboto entity type this field extends.
            display_name: Human-readable label shown in the UI. Defaults to ``None``.
            description: Longer description of the field's meaning.
            options: Type-specific configuration. Required for
                :py:attr:`~CustomFieldType.Enum` fields (to declare the allowed values).
            metadata_path: Reserved for promoting an existing metadata key into a
                custom field. Not yet supported; leave as ``None``.
            caller_org_id: Organization that should own the field. If omitted, the field is
                created in the caller's organization.
            roboto_client: Roboto client instance. Uses the default if omitted.

        Returns:
            The newly created CustomField. Its :py:attr:`status` is typically
            ``Creating``; call :py:meth:`wait_to_be_ready` to block until it is
            ``Ready``.

        Raises:
            RobotoConflictException: A field with this ``field_name`` and ``entity_type``
                already exists in the target org.
            RobotoInvalidRequestException: The request fails validation (e.g., a
                ``field_name`` that does not match the regex, an enum field without
                ``options``, or ``options`` whose ``field_type`` does not match
                ``field_type``).
            RobotoLimitExceededException: The limit on custom field definitions has
                been reached for the target organization and Roboto entity type.
            RobotoUnauthorizedException: The caller is not an administrator in the target org.

        Examples:
            Define a string field on datasets:

            >>> field = CustomField.create(
            ...     field_name="flight_id",
            ...     field_type=CustomFieldType.String,
            ...     entity_type=TargetEntityType.Dataset,
            ...     display_name="Flight ID",
            ... )
            >>> field.wait_to_be_ready()

            Define an enum field with a fixed set of allowed values:

            >>> from roboto.domain.custom_fields import EnumFieldOptions
            >>> field = CustomField.create(
            ...     field_name="severity",
            ...     field_type=CustomFieldType.Enum,
            ...     entity_type=TargetEntityType.Event,
            ...     options=EnumFieldOptions(enum_values=["low", "medium", "high"]),
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        request = CreateCustomFieldRequest(
            field_name=field_name,
            field_type=field_type,
            entity_type=entity_type,
            display_name=display_name,
            description=description,
            options=options,
            metadata_path=metadata_path,
        )

        record = roboto_client.post(path="v1/custom-fields", data=request, caller_org_id=caller_org_id).to_record(
            CustomFieldRecord
        )

        return cls(record, roboto_client)

    @classmethod
    def from_id(cls, field_id: str, roboto_client: typing.Optional[RobotoClient] = None) -> CustomField:
        """Load an existing custom field by its ``field_id``.

        Args:
            field_id: Opaque identifier assigned at create time.
            roboto_client: Roboto client instance. Uses the default if omitted.

        Returns:
            The CustomField with this ``field_id``.

        Raises:
            RobotoNotFoundException: No field with this ``field_id`` is visible to
                the caller.

        Examples:
            >>> field = CustomField.from_id("cf_abc123")
            >>> field.field_name
            'flight_id'
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        record = roboto_client.get(path=f"v1/custom-fields/id/{field_id}").to_record(CustomFieldRecord)

        return cls(record, roboto_client)

    @classmethod
    def from_name_and_entity_type(
        cls,
        field_name: str,
        entity_type: TargetEntityType,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> CustomField:
        """Load a custom field by ``field_name`` and ``entity_type``.

        Field names are unique within an ``(org_id, entity_type)`` pair, so the name
        plus the entity type fully qualifies a field within a given org.

        Args:
            field_name: Name of the field, as supplied to :py:meth:`create`.
            entity_type: Entity type the field extends.
            owner_org_id: Organization that owns the field. If omitted, searches the
                caller's organization.
            roboto_client: Roboto client instance. Uses the default if omitted.

        Returns:
            The matching CustomField.

        Raises:
            RobotoNotFoundException: No field with this name and entity type exists
                in the target org.
            RobotoUnauthorizedException: The caller is not authorized to retrieve the field.

        Examples:
            >>> field = CustomField.from_name_and_entity_type(
            ...     field_name="flight_id",
            ...     entity_type=TargetEntityType.Dataset,
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        quoted_name = urllib.parse.quote_plus(field_name)

        record = roboto_client.get(
            path=f"v1/custom-fields/name/{quoted_name}/entity-type/{entity_type.url_safe_value}",
            owner_org_id=owner_org_id,
        ).to_record(CustomFieldRecord)

        return cls(record, roboto_client)

    @classmethod
    def list(
        cls,
        entity_type: typing.Optional[TargetEntityType] = None,
        statuses: typing.Optional[collections.abc.Sequence[CustomFieldStatus]] = None,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator[CustomField, None, None]:
        """Yield custom fields visible to the caller, optionally filtered by entity type and status.

        By default, only fields in ``Creating``, ``Ready``, or ``Failed`` are returned;
        fields in ``Deleting`` are excluded because they are on their way out. Pass
        ``statuses=`` explicitly to override this.

        Args:
            entity_type: If provided, restrict results to fields targeting this
                entity type.
            statuses: If provided, restrict results to fields in any of these statuses.
                Defaults to ``(Creating, Ready, Failed)``.
            owner_org_id: Organization to list fields from. If omitted, lists fields in the
                caller's organization.
            roboto_client: Roboto client instance. Uses the default if omitted.

        Yields:
            CustomField instances matching the filters, in pages transparently fetched
            as the generator is consumed.

        Examples:
            List every Ready field on datasets in the caller's org:

            >>> for field in CustomField.list(
            ...     entity_type=TargetEntityType.Dataset,
            ...     statuses=[CustomFieldStatus.Ready],
            ... ):
            ...     print(field.field_name, field.field_type)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        defaulted_statuses = list(
            statuses or (CustomFieldStatus.Creating, CustomFieldStatus.Ready, CustomFieldStatus.Failed)
        )

        page_token: typing.Optional[str] = None

        while True:
            result_page = roboto_client.post(
                path="v1/custom-fields/query",
                data=ListCustomFieldsRequest(
                    page_token=page_token, entity_type=entity_type, statuses=defaulted_statuses
                ),
                idempotent=True,
                owner_org_id=owner_org_id,
            ).to_paginated_list(CustomFieldRecord)

            for record in result_page.items:
                yield cls(record, roboto_client)

            if not result_page.next_token:
                break

            page_token = result_page.next_token

    def __init__(self, record: CustomFieldRecord, roboto_client: RobotoClient) -> None:
        self.__record = record
        self.__roboto_client = roboto_client

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def created(self) -> datetime.datetime:
        """UTC timestamp when this field was defined."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """User ID that defined this field."""
        return self.__record.created_by

    @property
    def description(self) -> typing.Optional[str]:
        """Long-form description of the field's meaning, or ``None`` if unset."""
        return self.__record.description

    @property
    def display_name(self) -> typing.Optional[str]:
        """Human-readable label for the field, or ``None``."""
        return self.__record.display_name

    @property
    def entity_type(self) -> TargetEntityType:
        """Roboto entity type this field extends."""
        return self.__record.entity_type

    @property
    def field_id(self) -> str:
        """Opaque, globally unique identifier for this field."""
        return self.__record.field_id

    @property
    def field_name(self) -> str:
        """Name of the field, unique within ``(org_id, entity_type)`` and fixed at creation time."""
        return self.__record.field_name

    @property
    def field_type(self) -> CustomFieldType:
        """Value type of the field. Fixed at creation time."""
        return self.__record.field_type

    @property
    def last_error(self) -> typing.Optional[str]:
        """Human-readable summary of the most recent failure, if any.

        Populated when :py:attr:`status` is :py:attr:`CustomFieldStatus.Failed`, and may
        stay set until the next failure or success.
        """
        return self.__record.last_error

    @property
    def metadata_path(self) -> typing.Optional[str]:
        """Source metadata key the field was promoted from, if any. Reserved for future use."""
        return self.__record.metadata_path

    @property
    def modified(self) -> datetime.datetime:
        """UTC timestamp of the field's most recent status or other change."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """User ID of the most recent modifier. May be a system identity for automatic status changes."""
        return self.__record.modified_by

    @property
    def options(self) -> typing.Optional[CustomFieldOptions]:
        """Type-specific configuration, or ``None`` if the field type takes none.

        For enum fields this carries the allowed values and is required.
        """
        return self.__record.options

    @property
    def org_id(self) -> str:
        """Organization that owns this field."""
        return self.__record.org_id

    @property
    def status(self) -> CustomFieldStatus:
        """Current lifecycle status. See the class docstring for the state machine."""
        return self.__record.status

    def delete(self) -> None:
        """Delete this custom field.

        Returns as soon as the field has been moved to
        :py:attr:`~CustomFieldStatus.Deleting`. From the caller's perspective the
        field is gone at that point: values can no longer be set, and the field
        will shortly disappear from query results. The rest of the removal happens
        asynchronously; call :py:meth:`wait_to_be_deleted` if you need to know when
        it has finished.

        Only administrators in the target organization can delete custom fields.

        Raises:
            RobotoUnauthorizedException: The caller lacks permission to delete this
                field.

        Examples:
            >>> field = CustomField.from_name_and_entity_type("flight_id", TargetEntityType.Dataset)
            >>> field.delete()
            >>> field.wait_to_be_deleted()
        """
        self.__roboto_client.delete(path=f"v1/custom-fields/id/{self.field_id}", owner_org_id=self.org_id)

    def refresh(self) -> CustomField:
        """Re-fetch this field's record from the server and return ``self``.

        Useful for observing asynchronous state transitions (e.g., ``Creating`` →
        ``Ready``) without constructing a new object.

        Returns:
            This same CustomField, with its in-memory record replaced by a freshly
            fetched copy.

        Raises:
            RobotoNotFoundException: The field has been fully deleted.

        Examples:
            >>> field.refresh().status
            <CustomFieldStatus.Ready: 'ready'>
        """
        self.__record = CustomField.from_id(self.field_id, self.__roboto_client).__record
        return self

    def update(
        self,
        display_name: typing.Union[str, None, NotSetType] = NotSet,
        description: typing.Union[str, None, NotSetType] = NotSet,
    ) -> CustomField:
        """Update mutable metadata on this custom field in place.

        Passing :py:obj:`~roboto.sentinels.NotSet` (the default) leaves a field
        unchanged; passing ``None`` clears it.

        Only administrators in this field's organization can update it.

        Args:
            display_name: New display name, or ``None`` to clear it.
            description: New description, or ``None`` to clear it.

        Returns:
            This same CustomField, with its in-memory record replaced by the
            server's updated copy.

        Raises:
            RobotoNotFoundException: The field no longer exists.
            RobotoUnauthorizedException: The caller lacks permission to update this
                field.

        Examples:
            >>> field.update(display_name="Flight identifier")

            Clear the description:

            >>> field.update(description=None)
        """
        request = remove_not_set(UpdateCustomFieldRequest(display_name=display_name, description=description))

        updated_record = self.__roboto_client.post(
            path=f"v1/custom-fields/id/{self.field_id}", data=request, idempotent=True, owner_org_id=self.org_id
        ).to_record(CustomFieldRecord)

        self.__record = updated_record
        return self

    def wait_to_be_ready(self, timeout: float = 5 * 60, poll_interval: int = 2) -> None:
        """Block until this custom field reaches the :py:attr:`~CustomFieldStatus.Ready` state.

        Intended to be called immediately after :py:meth:`create` to know when the
        field is usable for setting values and querying.

        Args:
            timeout: Maximum time, in seconds, to wait. Most fields reach Ready well
                within the default; raise this value if you observe legitimate
                timeouts.
            poll_interval: Seconds to sleep between polls.

        Raises:
            RobotoInvalidStateTransitionException: The field is in a state from which
                it cannot reach Ready (``Failed`` or ``Deleting``), or it was deleted
                while waiting.
            roboto.waiters.TimeoutError: The field is still ``Creating`` after
                ``timeout`` seconds.

        Examples:
            >>> field = CustomField.create(
            ...     field_name="flight_id",
            ...     field_type=CustomFieldType.String,
            ...     entity_type=TargetEntityType.Dataset,
            ... )
            >>> field.wait_to_be_ready()
            >>> field.status
            <CustomFieldStatus.Ready: 'ready'>
        """

        def _condition() -> bool:
            try:
                self.refresh()
            except RobotoNotFoundException:
                raise RobotoInvalidStateTransitionException(
                    f"Custom field '{self.field_id}' was deleted while waiting for it to become Ready"
                ) from None

            if self.status == CustomFieldStatus.Ready:
                return True
            if self.status == CustomFieldStatus.Creating:
                return False

            raise RobotoInvalidStateTransitionException(
                f"Custom field '{self.field_id}' is in '{self.status}' state; will not reach Ready"
            )

        wait_for(
            _condition,
            timeout=timeout,
            interval=poll_interval,
            timeout_msg=f"Timed out waiting for custom field '{self.field_id}' to become Ready",
        )

    def wait_to_be_deleted(self, timeout: float = 5 * 60, poll_interval: int = 2) -> None:
        """Block until this custom field is fully deleted.

        Intended to be called immediately after :py:meth:`delete` to know when the
        field has been fully removed from the platform.

        Args:
            timeout: Maximum time, in seconds, to wait. Most fields are deleted well
                within the default; raise this value if you observe legitimate
                timeouts.
            poll_interval: Seconds to sleep between polls.

        Raises:
            RobotoInvalidStateTransitionException: The field is in a state from which
                it will not progress to deleted (``Ready``, ``Creating``, or
                ``Failed``). Call :py:meth:`delete` first.
            roboto.waiters.TimeoutError: The field is still ``Deleting`` after
                ``timeout`` seconds.

        Examples:
            >>> field.delete()
            >>> field.wait_to_be_deleted()
        """

        def _condition() -> bool:
            try:
                self.refresh()
            except RobotoNotFoundException:
                return True

            if self.status == CustomFieldStatus.Deleting:
                return False

            raise RobotoInvalidStateTransitionException(
                f"Custom field '{self.field_id}' is in '{self.status}' state; "
                "will not be deleted unless delete() is called"
            )

        wait_for(
            _condition,
            timeout=timeout,
            interval=poll_interval,
            timeout_msg=f"Timed out waiting for custom field '{self.field_id}' to be deleted",
        )
