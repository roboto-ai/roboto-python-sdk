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
    """A session event: a moment or span of interest in one session's data.

    An event belongs to one session, fixed when it is created, and spans an inclusive start and end time in
    nanoseconds since the Unix epoch. It can name topics, or fields of topics, to say which of the session's data it is
    about; naming none makes it about all of the session's data. It also carries tags, key-value metadata,
    custom-field values, and display options such as a color.

    These events are separate from the events that belong to a dataset, which :py:class:`~roboto.domain.events.Event`
    reads. Their IDs begin with ``evt_`` rather than ``ev_``, and each class reads only its own kind.

    Get an ``Event`` from ``create``, ``from_id``, or :py:meth:`~roboto.experimental.sessions.Session.list_events`. To
    wrap an ``EventRecord`` already fetched from Roboto, build an ``Event`` from it directly. Each instance holds a
    copy of the event's record: methods that change the event update that copy from Roboto's response, and ``refresh``
    fetches changes made elsewhere.

    Args:
        record: Record of the event.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
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
            name: Human-readable name of the event, such as ``"Takeoff"``. Roboto does not require names to be unique.
            session_id: ID of the session the event belongs to, beginning with ``se_``.
            start_time: Inclusive start of the event, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
            end_time: Inclusive end of the event, in the same form. ``None`` makes the event instantaneous, ending at
                ``start_time``.
            topics: Topics, or fields of topics, the event is about. Empty makes the event about all of the session's
                data.
            description: Human-readable description of the event. ``None`` sets none.
            tags: Tags to set on the event. ``None`` sets none.
            metadata: Key-value metadata to set on the event. ``None`` sets none.
            color: Display color of the event, as any CSS color value, such as ``"red"``. ``None`` lets Roboto choose a
                color.
            custom_fields: Values for the event's custom fields, keyed by field name. Each name must be a custom field
                defined for events in the organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
                field's type. ``None`` sets none.
            caller_org_id: Organization to create the event in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new event.

        Raises:
            RobotoFeatureNotAvailableException: The organization stores its events on datasets and files, not on
                sessions.
            RobotoIllegalArgumentException: A ``custom_fields`` name is not a ready custom field for events, or its
                value does not match the field's type.
            RobotoInvalidRequestException: The name is blank, the start is negative or after the end, the session is
                not in the organization, or ``topics`` is invalid: it names a topic twice, names a topic outside the
                organization, names a field ID that no schema of the topic's data in this session has, or gives an
                empty ``field_ids``.

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
        """Fetch a session event by its ID.

        Args:
            event_id: Unique ID of the event, beginning with ``evt_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No session event has this ID. A dataset event's ``ev_`` ID raises it too.

        Examples:
            >>> from roboto.experimental.events import Event
            >>> event = Event.from_id("evt_0123456789abcdef")
            >>> print(event.name)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v2/events/id/{event_id}").to_record(EventRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def delete_many(cls, event_ids: StrSequence, roboto_client: typing.Optional[RobotoClient] = None) -> None:
        """Delete several events, ignoring IDs that match no event.

        Sends the IDs one request per batch of 1000 (``MAX_EVENTS_PER_DELETE_BATCH``), in order. If the caller cannot
        delete one event of a batch, none of that batch is deleted and the call raises; batches sent before it stay
        deleted.

        Args:
            event_ids: IDs of the events to delete, each beginning with ``evt_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

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
        """Display color of the event, as a CSS color value, or ``None`` if Roboto chooses the color."""
        return self.__record.display_options.color if self.__record.display_options else None

    @property
    def created(self) -> datetime.datetime:
        """Time the event was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Principal that created the event, as ``<type>:<id>``, such as ``user:<user_id>``."""
        return self.__record.created_by

    @property
    def custom_fields(self) -> dict[str, typing.Any]:
        """Values of the custom fields the organization defines for events, keyed by field name.

        ``EventRecord.custom_fields`` says which fields appear as keys. Changing the returned dictionary does not
        change the event.
        """
        return dict(self.__record.custom_fields)

    @property
    def description(self) -> typing.Optional[str]:
        """Human-readable description of the event, or ``None`` if it has none."""
        return self.__record.description

    @property
    def display_options(self) -> typing.Optional[EventDisplayOptions]:
        """How the Roboto web app displays the event, such as its color, or ``None`` if no display options are set."""
        return self.__record.display_options

    @property
    def end_time(self) -> int:
        """Inclusive end of the event's time span, in nanoseconds since the Unix epoch."""
        return self.__record.end_time

    @property
    def event_id(self) -> str:
        """Unique ID of the event, beginning with ``evt_``."""
        return self.__record.event_id

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Copy of the key-value metadata on the event."""
        return dict(self.__record.metadata)

    @property
    def modified(self) -> datetime.datetime:
        """Time the event was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Principal that last modified the event, in the same ``<type>:<id>`` form as ``created_by``."""
        return self.__record.modified_by

    @property
    def name(self) -> str:
        """Human-readable name of the event, such as ``"Takeoff"``. Roboto does not require names to be unique."""
        return self.__record.name

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the event, which also owns the event's session."""
        return self.__record.org_id

    @property
    def record(self) -> EventRecord:
        """Record of the event that this instance holds.

        ``refresh`` replaces it with the current one.
        """
        return self.__record

    @property
    def session_id(self) -> str:
        """ID of the session the event belongs to. Fixed when the event is created."""
        return self.__record.session_id

    @property
    def start_time(self) -> int:
        """Inclusive start of the event's time span, in nanoseconds since the Unix epoch."""
        return self.__record.start_time

    @property
    def tags(self) -> list[str]:
        """Copy of the tags on the event."""
        return list(self.__record.tags)

    @property
    def topics(self) -> list[EventTopic]:
        """Topics, or fields of topics, the event is about, ordered by topic name.

        Empty when the event is about all of the session's data.
        """
        return list(self.__record.topics)

    def clear_custom_field(self, name: str) -> "Event":
        """Clear one custom-field value on the event, so that it reads ``None``.

        It calls ``update``, whose failures also apply.

        Args:
            name: Name of a custom field defined for events in the event's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: ``name`` is not a ready custom field for events.

        Examples:
            >>> event.clear_custom_field("root_cause")
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=[name]))

    def clear_custom_fields(self, names: StrSequence) -> "Event":
        """Clear custom-field values on the event, so that they read ``None``.

        It calls ``update``, whose failures also apply.

        Args:
            names: Names of custom fields defined for events in the event's organization, each with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: A name is not a ready custom field for events.

        Examples:
            >>> event.clear_custom_fields(["root_cause", "severity"])
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=list(names)))

    def delete(self) -> None:
        """Delete the event.

        Deleting an event that no longer exists succeeds and changes nothing.

        Examples:
            >>> from roboto.experimental.events import Event
            >>> Event.from_id("evt_0123456789abcdef").delete()
        """
        self.__roboto_client.delete(f"v2/events/id/{self.event_id}")

    def get_topic(self, topic_name: str) -> Topic:
        """Fetch a topic of the event's session by name, scoped to the event.

        The topic need not be one the event is about. It carries a ``roboto.experimental.topics.EventContext``, so its
        ``get_data*`` methods read only the data in the session's files, and by default only the event's time span,
        from ``start_time`` to ``end_time`` inclusive. Pass ``start_time`` and ``end_time`` to those methods to read
        around the event instead. Reading data requires the ``roboto[analytics]`` extra.

        Args:
            topic_name: Exact name of the topic, such as ``"/imu"``.

        Raises:
            RobotoNotFoundException: The event's session holds no data of a topic with this name.

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
        """Fetch the topics the event is about, ordered by topic name, scoped as ``get_topic`` scopes them.

        Makes one request per topic. An event about all of its session's data names no topic, so it returns an empty
        list. ``topics`` holds the fields the event names for each topic, in the same order; pass their IDs as
        ``fields_include`` to read only those fields.

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
        """Set metadata keys on the event, adding new keys and overwriting existing ones.

        Keys the dictionary does not name keep their values.

        Args:
            metadata: Key-value metadata to set on the event.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> event.put_metadata({"severity": "high"})
        """
        return self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(self, tags: StrSequence) -> "Event":
        """Add tags to the event, keeping its existing tags.

        Args:
            tags: Tags to add to the event.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> event.put_tags(["needs-review"])
        """
        return self.update(metadata_changeset=MetadataChangeset(put_tags=list(tags)))

    def refresh(self) -> "Event":
        """Replace this instance's record with the event's current record from Roboto.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoNotFoundException: The event no longer exists.

        Examples:
            >>> event.refresh()
        """
        self.__record = self.__roboto_client.get(f"v2/events/id/{self.event_id}").to_record(EventRecord)
        return self

    def remove_metadata(self, keys: StrSequence) -> "Event":
        """Remove metadata keys from the event.

        Args:
            keys: Metadata keys to remove.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> event.remove_metadata(["severity"])
        """
        return self.update(metadata_changeset=MetadataChangeset(remove_fields=list(keys)))

    def remove_tags(self, tags: StrSequence) -> "Event":
        """Remove tags from the event.

        Args:
            tags: Tags to remove from the event.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> event.remove_tags(["needs-review"])
        """
        return self.update(metadata_changeset=MetadataChangeset(remove_tags=list(tags)))

    def set_color(self, color: typing.Optional[str]) -> "Event":
        """Set the event's display color.

        Args:
            color: Display color of the event, as any CSS color value, such as ``"#ff0000"``. ``None`` clears it, so
                Roboto chooses one.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> event.set_color("#ff0000")
        """
        return self.update(display_options_changeset=EventDisplayOptionsChangeset(color=color))

    def set_custom_field(self, name: str, value: typing.Any) -> "Event":
        """Set one custom-field value on the event.

        It calls ``update``, whose failures also apply.

        Args:
            name: Name of a custom field defined for events in the event's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`.
            value: Value to set, which must match the field's type.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: ``name`` is not a ready custom field for events, or ``value`` does not
                match its type.

        Examples:
            >>> event.set_custom_field("root_cause", "wind")
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields={name: value}))

    def set_custom_fields(self, values: dict[str, typing.Any]) -> "Event":
        """Set custom-field values on the event. Fields the dictionary does not name keep their values.

        It calls ``update``, whose failures also apply.

        Args:
            values: Values to set, keyed by field name. Each name must be a custom field defined for events in the
                event's organization, with status :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`,
                and each value must match that field's type.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: A name is not a ready custom field for events, or a value does not match
                its field's type.

        Examples:
            >>> event.set_custom_fields({"root_cause": "wind"})
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields=values))

    def set_description(self, description: typing.Optional[str]) -> "Event":
        """Set the event's description.

        Args:
            description: Human-readable description of the event. ``None`` clears it.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> event.set_description("Checked against the flight log")
        """
        return self.update(description=description)

    def set_name(self, name: str) -> "Event":
        """Rename the event.

        It calls ``update``, whose failures also apply.

        Args:
            name: Human-readable name of the event. Roboto does not require names to be unique.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoInvalidRequestException: ``name`` is blank.

        Examples:
            >>> event.set_name("Hard landing (confirmed)")
        """
        return self.update(name=name)

    def set_topics(self, topics: collections.abc.Sequence[EventTopicRequest]) -> "Event":
        """Replace the topics, or fields of topics, the event is about.

        It calls ``update``, whose failures also apply.

        Args:
            topics: Topics, or fields of topics, the event is about. Empty makes the event about all of its session's
                data.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoInvalidRequestException: ``topics`` is invalid, as ``create`` describes.

        Examples:
            >>> from roboto.experimental.events import EventTopicRequest
            >>> event.set_topics([EventTopicRequest(topic_id="ti_0123456789ab")])
        """
        return self.update(topics=list(topics))

    def to_dict(self) -> dict[str, typing.Any]:
        """Return the record this instance holds, as a JSON-compatible dictionary.

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
        """Update the event's properties. Arguments left at their default (``NotSet`` or ``None``) are unchanged.

        An event's session cannot change.

        Args:
            name: Human-readable name of the event. Roboto does not require names to be unique.
            description: Human-readable description of the event. ``None`` clears it.
            start_time: Inclusive start of the event, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
            end_time: Inclusive end of the event, in the same form. Once both time changes apply, the end must not be
                before the start.
            topics: Topics, or fields of topics, the event is about, replacing every one it names. Empty makes the
                event about all of its session's data.
            metadata_changeset: Changes to the event's tags and metadata.
            display_options_changeset: Changes to the event's display options.
            custom_fields_changeset: Changes to the event's custom-field values. Fields the changeset does not name
                keep their values. ``None`` changes none.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: The custom-field changeset names a field that is not a ready custom field
                for events, or sets a value that does not match its field's type.
            RobotoInvalidRequestException: The name is blank, a time is negative, the end is before the start, or
                ``topics`` is invalid, as ``create`` describes.
            RobotoNotFoundException: The event no longer exists.

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
