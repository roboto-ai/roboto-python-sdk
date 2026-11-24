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
    RobotoInvalidRequestException,
    RobotoInvalidStateTransitionException,
    RobotoNotFoundException,
)
from ...http import RobotoClient
from ...sentinels import NotSet, NotSetType, remove_not_set
from ...waiters import wait_for
from ...warnings import experimental
from .operations import CreateCustomFieldRequest, ListCustomFieldsRequest, UpdateCustomFieldRequest
from .record import (
    CustomFieldOptions,
    CustomFieldRecord,
    CustomFieldStatus,
    CustomFieldType,
    EnumFieldOptions,
    TargetEntityType,
)


@experimental
class CustomField:
    """A custom field: a typed field an organization defines for one entity type, such as datasets.

    Each entity of that type can hold a value for the field, set with the entity's own methods, such as
    :py:meth:`~roboto.domain.datasets.Dataset.set_custom_field`, and search can filter and sort by it. The field's
    ``field_type`` determines the values it accepts and how search can filter by it.

    A field's ``status`` determines what can be done with it, and
    :py:class:`~roboto.domain.custom_fields.CustomFieldStatus` describes each status. A new field is ``Creating`` while
    Roboto sets it up, and cannot hold values or be searched until it is ``Ready``. A deleted field is ``Deleting``
    until Roboto removes it. ``create`` and ``delete`` return before Roboto finishes; ``wait_to_be_ready`` and
    ``wait_to_be_deleted`` wait until it has.

    A field's name is unique among its organization's fields for its entity type. Each organization can define a
    limited number of custom fields for each entity type; fields being deleted do not count toward the limit.

    Get a ``CustomField`` from ``create``, ``from_id``, ``from_name_and_entity_type``, or ``list``. To wrap a
    :py:class:`~roboto.domain.custom_fields.CustomFieldRecord` already fetched from Roboto, build a ``CustomField``
    from it directly. Each instance holds a copy of the field's record: methods that change the field update that copy
    from Roboto's response, and ``refresh`` fetches changes made elsewhere.

    Args:
        record: Record of the custom field.
        roboto_client: Client to make requests to Roboto with.
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
        """Create a custom field for one entity type.

        Returns while the field is still :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Creating`: it
        cannot hold values or be searched until Roboto finishes setting it up, which ``wait_to_be_ready`` waits for.
        Only an administrator of the organization can create a custom field.

        Args:
            field_name: Name of the custom field, unique among the organization's fields for ``entity_type`` and
                fixed once the field is created. Must match ``^[a-z][a-z0-9_]{0,62}$``
                (:py:const:`~roboto.domain.custom_fields.CUSTOM_FIELD_NAME_PATTERN`): a lowercase ASCII letter, then
                up to 62 lowercase ASCII letters, digits, or underscores.
            field_type: Value type of the custom field, which determines the values it accepts and how search can
                filter by it.
            entity_type: Kind of entity the custom field applies to.
            display_name: Human-readable label for the custom field, shown in the Roboto web app, at most 128
                characters. ``None`` sets none.
            description: Human-readable description of the custom field, at most 256 characters. ``None`` sets none.
            options: Type-specific configuration. Required for an enum field, to declare its allowed values, which are
                normalized as :py:attr:`~roboto.domain.custom_fields.CreateCustomFieldRequest.options` describes.
                ``None`` for every other field type.
            metadata_path: Reserved for future use. Leave it ``None``: Roboto rejects any other value.
            caller_org_id: Organization to create the custom field in. Required when the caller belongs to more than
                one organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new custom field, with status ``Creating``.

        Raises:
            RobotoConflictException: The organization already has a custom field with this name for ``entity_type``.
            RobotoInvalidRequestException: ``field_name`` is a name Roboto reserves, or ``metadata_path`` is set.
            RobotoLimitExceededException: The organization already has as many custom fields for ``entity_type`` as
                it is allowed.
            RobotoUnauthorizedException: The caller is not an administrator of the organization.
            pydantic.ValidationError: ``field_name`` does not match the pattern, an enum field has no ``options``,
                ``options`` are for a different field type, or a value breaks a rule that
                :py:class:`~roboto.domain.custom_fields.CreateCustomFieldRequest` states. Raised before the request is
                sent.

        Examples:
            Create a string field on datasets:

            >>> field = CustomField.create(
            ...     field_name="flight_id",
            ...     field_type=CustomFieldType.String,
            ...     entity_type=TargetEntityType.Dataset,
            ...     display_name="Flight ID",
            ... )
            >>> field.wait_to_be_ready()

            Create an enum field with a fixed set of allowed values:

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
        """Fetch a custom field by its ID.

        Args:
            field_id: ID of the custom field, beginning with ``cf_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No custom field has this ID.

        Examples:
            >>> field = CustomField.from_id("cf_12345")
            >>> print(field.field_name)
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
        """Fetch a custom field by its name and entity type.

        A name is unique among an organization's fields for one entity type, so the name, the entity type, and the
        organization identify one field.

        Args:
            field_name: Name of the custom field.
            entity_type: Kind of entity the custom field applies to.
            owner_org_id: Organization that owns the custom field. Defaults to the organization the caller acts in.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: The organization has no custom field with this name for ``entity_type``.

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
        """List an organization's custom fields, optionally limited to one entity type and some statuses.

        Fetches the fields a page at a time as the generator is consumed.

        Args:
            entity_type: Kind of entity to list custom fields for. ``None`` lists the fields for every entity type.
            statuses: Statuses of the custom fields to list. ``None`` or an empty sequence lists the fields whose
                :py:class:`~roboto.domain.custom_fields.CustomFieldStatus` is ``Creating``, ``Ready``, or ``Failed``,
                leaving out those being deleted.
            owner_org_id: Organization whose custom fields to list. Defaults to the organization the caller acts in.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            Custom fields that match ``entity_type`` and ``statuses``.

        Examples:
            List the ready custom fields on datasets:

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
        """Time the custom field was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Principal that created the custom field, as ``<type>:<id>``, such as ``user:<user_id>``."""
        return self.__record.created_by

    @property
    def description(self) -> typing.Optional[str]:
        """Human-readable description of the custom field, or ``None`` if it has none."""
        return self.__record.description

    @property
    def display_name(self) -> typing.Optional[str]:
        """Human-readable label of the custom field, or ``None`` if it has none."""
        return self.__record.display_name

    @property
    def entity_type(self) -> TargetEntityType:
        """Kind of entity the custom field applies to. Fixed when the field is created."""
        return self.__record.entity_type

    @property
    def field_id(self) -> str:
        """Unique ID of the custom field, beginning with ``cf_``."""
        return self.__record.field_id

    @property
    def field_name(self) -> str:
        """Name of the custom field, unique among its organization's fields for its entity type.

        Fixed when the field is created.
        """
        return self.__record.field_name

    @property
    def field_type(self) -> CustomFieldType:
        """Value type of the custom field. Fixed when the field is created."""
        return self.__record.field_type

    @property
    def last_error(self) -> typing.Optional[str]:
        """Human-readable reason the custom field's most recent create or delete failed, or ``None``.

        Set when ``status`` becomes :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Failed`, and cleared when
        the field is deleted. Roboto sets it; no request does.
        """
        return self.__record.last_error

    @property
    def metadata_path(self) -> typing.Optional[str]:
        """Unused.

        :py:attr:`~roboto.domain.custom_fields.CustomFieldRecord.metadata_path` says why it is always ``None``.
        """
        return self.__record.metadata_path

    @property
    def modified(self) -> datetime.datetime:
        """Time the custom field was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Principal that last modified the custom field, in the same ``<type>:<id>`` form as ``created_by``.

        :py:attr:`~roboto.domain.custom_fields.CustomFieldRecord.modified_by` says when it is Roboto's own system user.
        """
        return self.__record.modified_by

    @property
    def options(self) -> typing.Optional[CustomFieldOptions]:
        """Type-specific configuration of the custom field.

        :py:attr:`~roboto.domain.custom_fields.CustomFieldRecord.options` says which field types set it.
        """
        return self.__record.options

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the custom field."""
        return self.__record.org_id

    @property
    def status(self) -> CustomFieldStatus:
        """Lifecycle state of the custom field, which determines what can be done with it."""
        return self.__record.status

    def delete(self) -> None:
        """Delete this custom field.

        Returns once Roboto has moved the field to :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Deleting`:
        from then on, values can no longer be set on it, and ``list`` leaves it out by default. Roboto then removes the
        field; ``wait_to_be_deleted`` waits until it has. Deleting a custom field that is already being deleted, or
        that no longer exists, succeeds and changes nothing. Only an administrator of the field's organization can
        delete it.

        This instance's ``status`` is not updated; ``refresh`` fetches it.

        Raises:
            RobotoUnauthorizedException: The caller is not an administrator of the field's organization.

        Examples:
            >>> field = CustomField.from_name_and_entity_type("flight_id", TargetEntityType.Dataset)
            >>> field.delete()
            >>> field.wait_to_be_deleted()
        """
        self.__roboto_client.delete(path=f"v1/custom-fields/id/{self.field_id}", owner_org_id=self.org_id)

    def refresh(self) -> CustomField:
        """Replace this instance's record with the custom field's current record from Roboto.

        Use it to see the status changes Roboto makes after the field is created or deleted.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoNotFoundException: Roboto has finished deleting the field.

        Examples:
            >>> print(field.refresh().status)
        """
        self.__record = CustomField.from_id(self.field_id, self.__roboto_client).__record
        return self

    def update(
        self,
        display_name: typing.Union[str, None, NotSetType] = NotSet,
        description: typing.Union[str, None, NotSetType] = NotSet,
        options: typing.Union[CustomFieldOptions, NotSetType] = NotSet,
    ) -> CustomField:
        """Update this custom field's display name, description, or options.

        An argument left unset (``NotSet``, the default) leaves that value unchanged. Roboto updates only a field
        whose status is :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`. Only an administrator of the
        field's organization can update it.

        Args:
            display_name: Human-readable label for the custom field, shown in the Roboto web app, at most 128
                characters. ``None`` clears it, as does text that is blank once surrounding whitespace is stripped.
            description: Human-readable description of the custom field, at most 256 characters. ``None`` clears it,
                as does text that is blank once surrounding whitespace is stripped.
            options: Type-specific configuration to replace the field's own, for this field's ``field_type``. For an
                enum field, ``enum_values`` must include every value the field already has: values can be added but
                not removed. Values are normalized as
                :py:attr:`~roboto.domain.custom_fields.CreateCustomFieldRequest.options` describes, and a value that
                repeats one the field already has is dropped rather than rejected. ``add_enum_values`` adds values
                without listing the existing ones.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoConflictException: ``options`` is set, and another update changed the field's options while this
                one was in progress. Refresh the field and try again.
            RobotoInvalidRequestException: The field is not ``Ready``, ``options`` are for a different field type, or
                ``options`` would remove an existing enum value.
            RobotoNotFoundException: The field no longer exists.
            RobotoUnauthorizedException: The caller is not an administrator of the field's organization.
            pydantic.ValidationError: ``display_name`` or ``description`` is too long, an enum value cannot be
                stored, or ``enum_values`` holds more than 250 distinct values. Raised before the request is sent.

        Examples:
            Change the field's display name:

            >>> field.update(display_name="Flight identifier")

            Add a value to an enum field:

            >>> from roboto.domain.custom_fields import EnumFieldOptions
            >>> field.update(options=EnumFieldOptions(enum_values=[*field.options.enum_values, "critical"]))

            Re-send a value the field already has: it keeps its place, and only the new value is appended:

            >>> field.options.enum_values
            ['low', 'medium', 'high']
            >>> updated = field.update(
            ...     options=EnumFieldOptions(enum_values=[*field.options.enum_values, "medium", "critical"])
            ... )
            >>> updated.options.enum_values
            ['low', 'medium', 'high', 'critical']

            Clear the description:

            >>> field.update(description=None)
        """
        request = remove_not_set(
            UpdateCustomFieldRequest(display_name=display_name, description=description, options=options)
        )

        updated_record = self.__roboto_client.post(
            path=f"v1/custom-fields/id/{self.field_id}", data=request, idempotent=True, owner_org_id=self.org_id
        ).to_record(CustomFieldRecord)

        self.__record = updated_record
        return self

    def add_enum_values(self, *values: str) -> CustomField:
        """Add values to the set this enum field accepts.

        Fetches the field's current values first, so that the update lists every value the field has, including any
        added since this instance was loaded: ``update`` rejects options that leave one out. Called with no values, it
        returns without making a request. The failures of ``refresh`` and ``update`` also apply.

        Args:
            *values: Values to accept, in addition to the field's current ones. Each is normalized as
                :py:attr:`~roboto.domain.custom_fields.CreateCustomFieldRequest.options` describes, and one that the
                field already has, once normalized, changes nothing. A field may hold at most 250 values.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoConflictException: Another update changed the field's options between this method's fetch and its
                update.
            RobotoInvalidRequestException: This field is not an enum field.

        Examples:
            >>> field.options.enum_values
            ['low', 'medium', 'high']
            >>> field.add_enum_values("critical").options.enum_values
            ['low', 'medium', 'high', 'critical']
        """
        if not values:
            return self

        self.refresh()

        current = self.options
        if not isinstance(current, EnumFieldOptions):
            raise RobotoInvalidRequestException(
                f"Custom field '{self.field_name}' is a '{self.field_type}' field; "
                "enum values can only be added to an enum field"
            )

        return self.update(options=EnumFieldOptions(enum_values=[*current.enum_values, *values]))

    def wait_to_be_ready(self, timeout: float = 5 * 60, poll_interval: int = 2) -> None:
        """Wait until this custom field is ``Ready``, refreshing this instance's record as it polls.

        Call it after ``create``: a field can hold values and be searched once its
        :py:class:`~roboto.domain.custom_fields.CustomFieldStatus` is ``Ready``.

        Args:
            timeout: Maximum time to wait, in seconds.
            poll_interval: Seconds to wait between polls.

        Raises:
            RobotoInvalidStateTransitionException: The field is or becomes ``Failed`` or ``Deleting``, or is deleted,
                so it will not become ``Ready``.
            roboto.waiters.TimeoutError: The field was still ``Creating`` after ``timeout`` seconds. It subclasses the
                built-in ``TimeoutError``.

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
        """Wait until Roboto has finished deleting this custom field, refreshing this instance's record as it polls.

        Call it after ``delete``.

        Args:
            timeout: Maximum time to wait, in seconds.
            poll_interval: Seconds to wait between polls.

        Raises:
            RobotoInvalidStateTransitionException: The field's
                :py:class:`~roboto.domain.custom_fields.CustomFieldStatus` is ``Creating``, ``Ready``, or ``Failed``:
                either it was never deleted, or its deletion failed.
            roboto.waiters.TimeoutError: The field was still ``Deleting`` after ``timeout`` seconds. It subclasses the
                built-in ``TimeoutError``.

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
