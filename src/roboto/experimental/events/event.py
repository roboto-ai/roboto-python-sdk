# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing
import urllib.parse

from ...domain.events import EventDisplayOptions, EventDisplayOptionsChangeset
from ...domain.topics.record import TopicIdentityRecord
from ...http import RobotoClient
from ...sentinels import NotSet, NotSetType, remove_not_set
from ...time import Time, to_epoch_nanoseconds
from ...updates import CustomFieldChangeset, MetadataChangeset, StrSequence
from ...warnings import experimental
from ..topics import EventContext, Topic
from .operations import (
    MAX_EVENTS_PER_DELETE_BATCH,
    CreateEventRequest,
    DeleteEventsRequest,
    EventTopicRequest,
    UpdateEventRequest,
)
from .record import EventRecord, EventTopic


@experimental
class Event:
    """A moment or span of interest in one session's data.

    An event belongs to exactly one session, fixed when it is created. It has a start and an end time in nanoseconds
    since the Unix epoch, and may name one or more topics, or fields of a topic, to say which of the session's data it
    is about. Like other Roboto entities it carries tags, metadata, custom-field values, and display options such as a
    color.

    These events are separate from the events that belong to a dataset, which :py:class:`roboto.domain.events.Event`
    reads: their IDs start with ``evt_`` rather than ``ev_``, and each class reads only its own kind.
    """

    __record: EventRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        name: str,
        session_id: str,
        start_time: Time,
        end_time: typing.Optional[Time] = None,
        topics: collections.abc.Sequence[EventTopicRequest] = (),
        description: typing.Optional[str] = None,
        tags: typing.Optional[StrSequence] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        color: typing.Optional[str] = None,
        custom_fields: typing.Optional[dict[str, typing.Any]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Event":
        """Create an event on a session.

        Args:
            name: A brief human-readable name, such as ``"Takeoff"``. Many events can share a name.
            session_id: The session the event belongs to.
            start_time: The start of the event, inclusive, as nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
            end_time: The end of the event, inclusive. Omit it for an instantaneous event.
            topics: The topics, or topic fields, the event is about. Empty means all of the session's data.
            description: An optional description.
            tags: Initial tags.
            metadata: Initial metadata.
            color: A CSS color to display the event in.
            custom_fields: Initial values for Ready custom fields defined on events in the caller's org.
            caller_org_id: The caller's org. Required when the caller belongs to several orgs.
            roboto_client: Optional RobotoClient; defaults to the ambient one.

        Returns:
            The created event.

        Raises:
            RobotoFeatureNotAvailableException: The caller's org does not have session events; its events belong to
                datasets and files.
            RobotoIllegalArgumentException: A custom field is not a Ready field on events, or its value does not
                satisfy the field's type.
            RobotoInvalidRequestException: The name is blank, the start is negative or after the end, the session is
                not in the caller's org, or ``topics`` is invalid: it names a topic twice, names a topic outside the
                caller's org, names a field ID that isn't in the topic's data in this session, or gives an
                empty ``field_ids``.
            RobotoUnauthorizedException: The caller is not a member of the org or may not view its sessions.

        Examples:
            Mark a hard landing on the IMU's vertical acceleration within a session:

            >>> from roboto.experimental.events import Event, EventTopicRequest
            >>> event = Event.create(
            ...     name="Hard landing",
            ...     session_id="se_0123456789ab",
            ...     start_time=1_722_870_127_000_000_000,
            ...     end_time=1_722_870_128_500_000_000,
            ...     topics=[EventTopicRequest(topic_id="ti_0123456789ab", field_ids=["sf_0123456789ab"])],
            ...     tags=["landing"],
            ...     color="red",
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateEventRequest(
            name=name,
            session_id=session_id,
            start_time=to_epoch_nanoseconds(start_time),
            end_time=to_epoch_nanoseconds(end_time) if end_time is not None else None,
            topics=list(topics),
            description=description,
            tags=list(tags or []),
            metadata=metadata or {},
            display_options=EventDisplayOptions(color=color) if color is not None else None,
            custom_fields=custom_fields,
        )
        record = roboto_client.post("v2/events", data=request, caller_org_id=caller_org_id).to_record(EventRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(cls, event_id: str, roboto_client: typing.Optional[RobotoClient] = None) -> "Event":
        """Load an event by its ID.

        Args:
            event_id: The event's ID, which starts with ``evt_``.
            roboto_client: Optional RobotoClient; defaults to the ambient one.

        Raises:
            RobotoNotFoundException: No session event has this ID. A dataset event's ``ev_*`` ID raises this too.
            RobotoUnauthorizedException: The caller may not view sessions in the event's org.

        Examples:
            >>> from roboto.experimental.events import Event
            >>> event = Event.from_id("evt_0123456789abcdef")
            >>> event.name
            'Hard landing'
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v2/events/id/{event_id}").to_record(EventRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def delete_many(cls, event_ids: StrSequence, roboto_client: typing.Optional[RobotoClient] = None) -> None:
        """Delete several events. IDs of events that do not exist are ignored.

        The IDs are sent in batches of :py:data:`~roboto.experimental.events.MAX_EVENTS_PER_DELETE_BATCH`, in order.
        If the caller may not delete one event of a batch, none of that batch is deleted and the call raises; batches
        sent before it stay deleted.

        Args:
            event_ids: IDs of the events to delete, each starting with ``evt_``.
            roboto_client: Optional RobotoClient; defaults to the ambient one.

        Raises:
            RobotoUnauthorizedException: The caller may not delete one of the events.

        Examples:
            >>> from roboto.experimental.events import Event
            >>> Event.delete_many(["evt_0123456789abcdef", "evt_fedcba9876543210"])
        """
        ids = list(event_ids)
        roboto_client = RobotoClient.defaulted(roboto_client)
        for start in range(0, len(ids), MAX_EVENTS_PER_DELETE_BATCH):
            roboto_client.post(
                "v2/events/delete", data=DeleteEventsRequest(event_ids=ids[start : start + MAX_EVENTS_PER_DELETE_BATCH])
            )

    def __init__(self, record: EventRecord, roboto_client: typing.Optional[RobotoClient] = None):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def color(self) -> typing.Optional[str]:
        """The CSS color the event is displayed in, or ``None`` for an automatically chosen one."""
        return self.__record.display_options.color if self.__record.display_options else None

    @property
    def created(self) -> datetime.datetime:
        """When the event was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """The user who created the event."""
        return self.__record.created_by

    @property
    def custom_fields(self) -> dict[str, typing.Any]:
        """Values of the custom fields defined on events in this event's org; an unset field reads ``None``."""
        return dict(self.__record.custom_fields)

    @property
    def description(self) -> typing.Optional[str]:
        """The event's description, if any."""
        return self.__record.description

    @property
    def display_options(self) -> typing.Optional[EventDisplayOptions]:
        """The event's display options, such as its color."""
        return self.__record.display_options

    @property
    def end_time(self) -> int:
        """The end of the event, inclusive, in nanoseconds since the Unix epoch."""
        return self.__record.end_time

    @property
    def event_id(self) -> str:
        """The event's unique ID (``evt_*``)."""
        return self.__record.event_id

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """The event's metadata."""
        return dict(self.__record.metadata)

    @property
    def modified(self) -> datetime.datetime:
        """When the event was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """The user who last modified the event."""
        return self.__record.modified_by

    @property
    def name(self) -> str:
        """The event's name."""
        return self.__record.name

    @property
    def org_id(self) -> str:
        """The org that owns the event and its session."""
        return self.__record.org_id

    @property
    def record(self) -> EventRecord:
        """The event's wire representation."""
        return self.__record

    @property
    def session_id(self) -> str:
        """The session the event belongs to."""
        return self.__record.session_id

    @property
    def start_time(self) -> int:
        """The start of the event, inclusive, in nanoseconds since the Unix epoch."""
        return self.__record.start_time

    @property
    def tags(self) -> list[str]:
        """The event's tags."""
        return list(self.__record.tags)

    @property
    def topics(self) -> list[EventTopic]:
        """The topics, or topic fields, the event is about. Empty means all of its session's data."""
        return list(self.__record.topics)

    def clear_custom_field(self, name: str) -> "Event":
        """Clear one custom-field value, so that it reads ``None``.

        Raises:
            RobotoIllegalArgumentException: ``name`` is not a Ready custom field on events.

        Examples:
            >>> event.clear_custom_field("root_cause")
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=[name]))

    def clear_custom_fields(self, names: StrSequence) -> "Event":
        """Clear custom-field values, so that they read ``None``.

        Raises:
            RobotoIllegalArgumentException: A name is not a Ready custom field on events.

        Examples:
            >>> event.clear_custom_fields(["root_cause", "severity"])
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=list(names)))

    def delete(self) -> None:
        """Delete this event. Deleting an event that no longer exists is not an error.

        Raises:
            RobotoUnauthorizedException: The caller may not delete the event.

        Examples:
            >>> from roboto.experimental.events import Event
            >>> Event.from_id("evt_0123456789abcdef").delete()
        """
        self.__roboto_client.delete(f"v2/events/id/{self.event_id}")

    def get_topic(self, topic_name: str) -> Topic:
        """Return the named topic of this event's session, scoped to the event.

        Works for any topic of the session, whether or not the event is about it. The topic carries an
        :py:class:`~roboto.experimental.topics.EventContext`, so its ``get_data*`` methods read only this session's
        data and default their read window to this event's span, from :py:attr:`start_time` to :py:attr:`end_time`
        inclusive. Pass ``start_time`` and ``end_time`` to them to read around the event instead. Requires the
        ``roboto[analytics]`` extra to read data.

        Args:
            topic_name: Exact name of the topic (e.g. ``"/imu"``).

        Raises:
            RobotoNotFoundException: The event's session holds no data of a topic with that name.

        Examples:
            Read the IMU data within the event:

            >>> from roboto.experimental.events import Event
            >>> event = Event.from_id("evt_0123456789abcdef")
            >>> df = event.get_topic("/imu").get_data_as_df()

            Read the GPS data from a second before the event to a second after it:

            >>> gps = event.get_topic("/gps").get_data_as_df(
            ...     start_time=event.start_time - 1_000_000_000, end_time=event.end_time + 1_000_000_000
            ... )
        """
        quoted_topic_name = urllib.parse.quote_plus(topic_name)
        record = self.__roboto_client.get(
            f"v1/sessions/id/{self.session_id}/topics/name/{quoted_topic_name}",
        ).to_record(TopicIdentityRecord)
        return Topic.from_record(record, roboto_client=self.__roboto_client, context=self.__topic_context())

    def get_topics(self) -> list[Topic]:
        """Return the topics this event is about, ordered by name, scoped as :py:meth:`get_topic` scopes them.

        An event about all of its session's data is about no topic in particular, and returns an empty list.
        The event's field IDs for a topic are in :py:attr:`topics`; pass them as ``fields_include`` to read only them.

        Examples:
            >>> from roboto.experimental.topics import FieldAddress
            >>> for topic, event_topic in zip(event.get_topics(), event.topics):
            ...     fields = [FieldAddress(field_id=field.field_id) for field in event_topic.fields or []]
            ...     df = topic.get_data_as_df(fields_include=fields or None)
        """
        return [
            Topic.from_id(event_topic.topic_id, roboto_client=self.__roboto_client, context=self.__topic_context())
            for event_topic in self.__record.topics
        ]

    def put_metadata(self, metadata: dict[str, typing.Any]) -> "Event":
        """Add or overwrite metadata keys.

        Examples:
            >>> event.put_metadata({"severity": "high"})
        """
        return self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(self, tags: StrSequence) -> "Event":
        """Add tags.

        Examples:
            >>> event.put_tags(["needs-review"])
        """
        return self.update(metadata_changeset=MetadataChangeset(put_tags=list(tags)))

    def refresh(self) -> "Event":
        """Reload this event from Roboto.

        Examples:
            >>> event.refresh()
        """
        self.__record = self.__roboto_client.get(f"v2/events/id/{self.event_id}").to_record(EventRecord)
        return self

    def remove_metadata(self, keys: StrSequence) -> "Event":
        """Remove metadata keys.

        Examples:
            >>> event.remove_metadata(["severity"])
        """
        return self.update(metadata_changeset=MetadataChangeset(remove_fields=list(keys)))

    def remove_tags(self, tags: StrSequence) -> "Event":
        """Remove tags.

        Examples:
            >>> event.remove_tags(["needs-review"])
        """
        return self.update(metadata_changeset=MetadataChangeset(remove_tags=list(tags)))

    def set_color(self, color: typing.Optional[str]) -> "Event":
        """Set the CSS color the event is displayed in, or ``None`` to use an automatically chosen one.

        Examples:
            >>> event.set_color("#ff0000")
        """
        return self.update(display_options_changeset=EventDisplayOptionsChangeset(color=color))

    def set_custom_field(self, name: str, value: typing.Any) -> "Event":
        """Set one value of a Ready custom field defined on events in this event's org.

        Raises:
            RobotoIllegalArgumentException: ``name`` is not a Ready custom field on events, or ``value`` does not
                satisfy its type.

        Examples:
            >>> event.set_custom_field("root_cause", "wind")
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields={name: value}))

    def set_custom_fields(self, values: dict[str, typing.Any]) -> "Event":
        """Set values of Ready custom fields defined on events in this event's org.

        Raises:
            RobotoIllegalArgumentException: A name is not a Ready custom field on events, or a value does not satisfy
                its field's type.

        Examples:
            >>> event.set_custom_fields({"root_cause": "wind"})
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields=values))

    def set_description(self, description: typing.Optional[str]) -> "Event":
        """Set the event's description, or ``None`` to clear it.

        Examples:
            >>> event.set_description("Checked against the flight log")
        """
        return self.update(description=description)

    def set_name(self, name: str) -> "Event":
        """Rename the event.

        Raises:
            RobotoInvalidRequestException: ``name`` is blank.

        Examples:
            >>> event.set_name("Hard landing (confirmed)")
        """
        return self.update(name=name)

    def set_topics(self, topics: collections.abc.Sequence[EventTopicRequest]) -> "Event":
        """Replace the topics, or topic fields, the event is about.

        An empty list makes the event about all of its session's data.

        Raises:
            RobotoInvalidRequestException: ``topics`` is invalid, as described on :py:meth:`create`.

        Examples:
            >>> from roboto.experimental.events import EventTopicRequest
            >>> event.set_topics([EventTopicRequest(topic_id="ti_0123456789ab")])
        """
        return self.update(topics=list(topics))

    def to_dict(self) -> dict[str, typing.Any]:
        """Return the event's record as a dictionary of JSON-compatible values.

        Examples:
            >>> import json
            >>> json.dumps(event.to_dict())
        """
        return self.__record.model_dump(mode="json")

    def update(
        self,
        name: typing.Union[str, NotSetType] = NotSet,
        description: typing.Union[str, None, NotSetType] = NotSet,
        start_time: typing.Union[Time, NotSetType] = NotSet,
        end_time: typing.Union[Time, NotSetType] = NotSet,
        topics: typing.Union[collections.abc.Sequence[EventTopicRequest], NotSetType] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
        display_options_changeset: typing.Union[EventDisplayOptionsChangeset, NotSetType] = NotSet,
        custom_fields_changeset: typing.Optional[CustomFieldChangeset] = None,
    ) -> "Event":
        """Change mutable fields of this event; arguments left ``NotSet`` keep their values. The session cannot change.

        Args:
            name: A new name.
            description: A new description, or ``None`` to clear it.
            start_time: A new start time.
            end_time: A new end time. The resulting end must not be before the resulting start.
            topics: A replacement for every topic, or topic field, the event is about.
            metadata_changeset: Tag and metadata changes.
            display_options_changeset: Display option changes.
            custom_fields_changeset: Custom-field value changes.

        Returns:
            This event, refreshed from the response.

        Raises:
            RobotoIllegalArgumentException: The changeset names a custom field that is not a Ready field on events,
                or sets a value that does not satisfy its field's type.
            RobotoInvalidRequestException: The update is invalid, such as a blank name, a negative time, an end before
                the start, or ``topics`` that is invalid as described on :py:meth:`create`.
            RobotoNotFoundException: The event no longer exists.
            RobotoUnauthorizedException: The caller is not a member of the event's org or may not view its sessions.

        Examples:
            >>> event.update(name="Hard landing (confirmed)", description="Checked against the flight log")
        """
        request = remove_not_set(
            UpdateEventRequest(
                name=name,
                description=description,
                start_time=to_epoch_nanoseconds(start_time) if not isinstance(start_time, NotSetType) else NotSet,
                end_time=to_epoch_nanoseconds(end_time) if not isinstance(end_time, NotSetType) else NotSet,
                topics=list(topics) if not isinstance(topics, NotSetType) else NotSet,
                metadata_changeset=metadata_changeset,
                display_options_changeset=display_options_changeset,
                custom_fields_changeset=custom_fields_changeset,
            )
        )
        self.__record = self.__roboto_client.put(f"v2/events/id/{self.event_id}", data=request).to_record(EventRecord)
        return self

    def __topic_context(self) -> EventContext:
        return EventContext(
            event_id=self.event_id, session_id=self.session_id, start_time=self.start_time, end_time=self.end_time
        )
