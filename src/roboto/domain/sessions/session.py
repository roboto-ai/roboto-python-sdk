# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing

from ...http import RobotoClient
from ...sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)
from ...warnings import experimental
from ..files import File
from ..topics.record import TopicIdentityRecord
from .operations import (
    AddFilesRequest,
    AttachToDeviceRequest,
    CreateSessionRequest,
    DetachFromDeviceRequest,
    RemoveFilesRequest,
    SessionFile,
    SessionUpdate,
)
from .record import SessionRecord


@experimental
class Session:
    """An operational time window of a Device.

    A Session is a drone flight, a vehicle drive, a robot arm test run — some contiguous activity
    in the real world. It groups the recordings, logs, and other data produced during that window.
    Because a Session is bounded by the activity rather than by the recordings, it can span many
    files or cover just a slice of one. Files participate as contributions, each optionally narrowed
    to a sub-window of the file.

    The Session's aggregate bounds — ``min_timestamp_ns`` and ``max_timestamp_ns``, in Unix-epoch
    nanoseconds — are recomputed by Roboto across all file contributions on every add or remove, and the
    returned instance reflects the updated bounds.

    A Session can reference one or many devices: a single drone for a solo mission, or all of the
    drones in a formation flight. Use :py:meth:`attach_to_device` and :py:meth:`detach_from_device`
    to change which devices it references.

    How to create a Session:

    * :py:meth:`Session.create` accepts zero, one, or many devices.
    * :py:meth:`~roboto.domain.devices.Device.create_session` is a shortcut for the common
      single-device case.
    * :py:meth:`~roboto.domain.datasets.Dataset.create_session` creates a Session for an existing
      Dataset, inferring the devices involved and pre-populating files from the Dataset.

    Once created, include files with :py:meth:`add_file` or :py:meth:`add_files`.

    Examples:
        Create a Session for a drone flight, include a recording, and list its topics:

        >>> from roboto.domain.sessions import Session
        >>> session = Session.create(name="flight-2026-04-23-001", device_ids=["dv_abc"])
        >>> session = session.add_file("fl_0123456789abcdef")
        >>> for topic in session.list_topics():
        ...     print(topic.name)
    """

    __roboto_client: RobotoClient
    __record: SessionRecord

    @classmethod
    def create(
        cls,
        name: typing.Optional[str] = None,
        device_ids: collections.abc.Sequence[str] = (),
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Session":
        """Create a new Session, optionally associating it with one or more devices.

        Prefer :py:meth:`~roboto.domain.devices.Device.create_session` for the common single-device
        case. To add devices to an existing Session later, see :py:meth:`attach_to_device`.

        Args:
            name: Optional short name for the Session (max 120 characters).
            device_ids: Devices to associate with the Session at creation.
                Empty (the default) creates a Session with no associated devices.
            caller_org_id: Caller's org scope. Required when the caller belongs to multiple orgs.
            roboto_client: Optional RobotoClient; defaults to the ambient one.

        Returns:
            The created Session.

        Examples:
            >>> from roboto.domain.sessions import Session
            >>> session = Session.create(name="flight-2026-04-23-001", device_ids=["dv_a", "dv_b"])
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateSessionRequest(name=name, device_ids=list(device_ids))
        record = roboto_client.post(
            "v1/sessions",
            data=request,
            caller_org_id=caller_org_id,
        ).to_record(SessionRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(
        cls,
        session_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Session":
        """Load a Session by ID.

        Args:
            session_id: Session primary key.
            owner_org_id: Caller's org scope. Required when the caller belongs to multiple orgs.
            roboto_client: Optional RobotoClient; defaults to the ambient one.

        Returns:
            The Session.
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/sessions/id/{session_id}",
            owner_org_id=owner_org_id,
        ).to_record(SessionRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_dataset(
        cls,
        dataset_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Session", None, None]:
        """Iterate Sessions whose composition includes any file in the given dataset.

        Args:
            dataset_id: Dataset whose sessions to list.
            owner_org_id: Org that owns the dataset. Required when the caller belongs to multiple orgs.
            roboto_client: Optional RobotoClient; defaults to the ambient one.

        Yields:
            Sessions, one at a time, following pagination automatically.

        Examples:
            >>> from roboto.domain.sessions import Session
            >>> for session in Session.for_dataset("ds_abc"):
            ...     print(session.session_id, session.name)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token

            results = roboto_client.get(
                f"v1/datasets/{dataset_id}/sessions",
                owner_org_id=owner_org_id,
                query=query,
            ).to_paginated_list(SessionRecord)

            for item in results.items:
                yield cls(record=item, roboto_client=roboto_client)

            next_token = results.next_token
            if not next_token:
                break

    @classmethod
    def for_org(
        cls,
        org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Session", None, None]:
        """Iterate all Sessions visible to the caller's org.

        Args:
            org_id: Caller's org scope. Required when the caller belongs to multiple orgs.
            roboto_client: Optional RobotoClient; defaults to the ambient one.

        Yields:
            Sessions, one at a time, following pagination automatically.
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token

            results = roboto_client.get(
                "v1/sessions",
                caller_org_id=org_id,
                query=query,
            ).to_paginated_list(SessionRecord)

            for item in results.items:
                yield cls(record=item, roboto_client=roboto_client)

            next_token = results.next_token
            if not next_token:
                break

    def __init__(
        self,
        record: SessionRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> None:
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def created(self) -> typing.Optional[datetime.datetime]:
        """UTC timestamp when this Session was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Identifier of the user or service which created this Session."""
        return self.__record.created_by

    @property
    def max_timestamp_ns(self) -> typing.Optional[int]:
        """Upper aggregate bound across this Session's recording data contributions, in Unix-epoch nanoseconds.

        ``None`` when the Session has no contributions.
        """
        return self.__record.max_timestamp_ns

    @property
    def min_timestamp_ns(self) -> typing.Optional[int]:
        """Lower aggregate bound across this Session's recording data contributions, in Unix-epoch nanoseconds.

        ``None`` when the Session has no contributions.
        """
        return self.__record.min_timestamp_ns

    @property
    def modified(self) -> typing.Optional[datetime.datetime]:
        """UTC timestamp when this Session was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Identifier of the user or service which last modified this Session."""
        return self.__record.modified_by

    @property
    def name(self) -> typing.Optional[str]:
        """Optional short name of this Session."""
        return self.__record.name

    @property
    def org_id(self) -> str:
        """Identifier of the organization that owns this Session."""
        return self.__record.org_id

    @property
    def record(self) -> SessionRecord:
        """Underlying data record for this Session."""
        return self.__record

    @property
    def session_id(self) -> str:
        """Globally unique identifier assigned to this Session on creation."""
        return self.__record.session_id

    def attach_to_device(self, device_id: str) -> None:
        """Attach a Device to this Session as a subject.

        A Session may have many device subjects — for example, a formation flight where multiple drones operate within
        a single activity window.

        Args:
            device_id: ID of the Device to add as a subject of this Session.

        Examples:
            >>> session.attach_to_device("dv_wingman")
            >>> list(session.list_devices())
            ['dv_lead', 'dv_wingman']
        """
        self.__roboto_client.post(
            f"v1/sessions/id/{self.session_id}/devices",
            data=AttachToDeviceRequest(device_id=device_id),
            owner_org_id=self.org_id,
        )

    def add_file(
        self,
        file: typing.Union[File, str],
        range_min_timestamp_ns: typing.Optional[int] = None,
        range_max_timestamp_ns: typing.Optional[int] = None,
    ) -> "Session":
        """Include a single file in this Session as a contribution.

        Thin convenience over :py:meth:`add_files` for the common one-file case.

        Args:
            file: A :py:class:`~roboto.domain.files.File` or a raw file id.
            range_min_timestamp_ns: Optional lower bound (Unix-epoch nanoseconds) of this file's contribution to
                the Session. Must be paired with ``range_max_timestamp_ns``; leaving both ``None`` contributes the
                whole file's time window.
            range_max_timestamp_ns: Optional upper bound paired with ``range_min_timestamp_ns``.

        Returns:
            This Session, with recomputed aggregate bounds (``min_timestamp_ns`` / ``max_timestamp_ns``).

        Examples:
            Include a whole file:

            >>> session.add_file("fl_0123456789abcdef")

            Include only a sub-window of a file:

            >>> session.add_file(
            ...     "fl_0123456789abcdef",
            ...     range_min_timestamp_ns=1_700_000_000_000_000_000,
            ...     range_max_timestamp_ns=1_700_000_060_000_000_000,
            ... )
        """
        file_id = file.file_id if isinstance(file, File) else file
        return self.add_files(
            [
                SessionFile(
                    file_id=file_id,
                    range_min_timestamp_ns=range_min_timestamp_ns,
                    range_max_timestamp_ns=range_max_timestamp_ns,
                )
            ]
        )

    def add_files(self, files: collections.abc.Sequence[SessionFile]) -> "Session":
        """Include the given files in this Session as contributions.

        Each file may carry optional ``range_min_timestamp_ns`` / ``range_max_timestamp_ns`` bounds
        (Unix-epoch nanoseconds) narrowing its contribution to a sub-window of the file's data.
        The service recomputes the Session's aggregate bounds across all contributions, and the
        Session instance reflects the new ``min_timestamp_ns`` / ``max_timestamp_ns`` on return.

        Args:
            files: Files to contribute to the Session.

        Returns:
            This Session, with recomputed aggregate bounds (``min_timestamp_ns`` / ``max_timestamp_ns``).

        Examples:
            >>> from roboto.domain.sessions import SessionFile
            >>> session.add_files(
            ...     [
            ...         SessionFile(file_id="fl_aaa"),
            ...         SessionFile(
            ...             file_id="fl_bbb",
            ...             range_min_timestamp_ns=1_700_000_000_000_000_000,
            ...             range_max_timestamp_ns=1_700_000_060_000_000_000,
            ...         ),
            ...     ]
            ... )
        """
        record = self.__roboto_client.post(
            f"v1/sessions/id/{self.session_id}/files",
            data=AddFilesRequest(files=list(files)),
            owner_org_id=self.org_id,
        ).to_record(SessionRecord)
        self.__record = record
        return self

    def delete(self) -> None:
        """Delete this Session. Its file contributions and device attachments are removed alongside it."""
        self.__roboto_client.delete(
            f"v1/sessions/id/{self.session_id}",
            owner_org_id=self.org_id,
        )

    def list_devices(self) -> collections.abc.Generator[str, None, None]:
        """Iterate the device IDs attached as subjects of this Session, paginated."""
        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token

            page = self.__roboto_client.get(
                f"v1/sessions/id/{self.session_id}/devices",
                owner_org_id=self.org_id,
                query=query,
            ).to_dict(json_path=["data"])

            for item in page["items"]:
                yield str(item)

            next_token = page["next_token"]
            if not next_token:
                break

    def list_files(self) -> collections.abc.Generator[SessionFile, None, None]:
        """Iterate this Session's file contributions, following pagination automatically.

        Yields:
            :py:class:`SessionFile` entries, each carrying its optional ``range_min_timestamp_ns`` /
            ``range_max_timestamp_ns`` sub-window bounds.
        """
        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token

            page = self.__roboto_client.get(
                f"v1/sessions/id/{self.session_id}/files",
                owner_org_id=self.org_id,
                query=query,
            ).to_paginated_list(SessionFile)

            yield from page.items

            next_token = page.next_token
            if not next_token:
                break

    def list_topics(self) -> collections.abc.Generator[TopicIdentityRecord, None, None]:
        """Iterate topic identities reachable from this Session, following pagination.

        Results are range-filtered: a topic identity is yielded only when the Session's time window overlaps at least
        one of the topic's timeline extents (:py:class:`~roboto.domain.topics.TimelineExtentRecord`). Results are
        deduplicated across files and partitions, ordered by ``name`` with ``topic_id`` as a deterministic tiebreaker.

        Yields:
            :py:class:`roboto.domain.topics.TopicIdentityRecord` entries.

        Examples:
            >>> for topic in session.list_topics():
            ...     print(topic.topic_id, topic.name)
        """
        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token

            page = self.__roboto_client.get(
                f"v1/sessions/id/{self.session_id}/topics",
                owner_org_id=self.org_id,
                query=query,
            ).to_paginated_list(TopicIdentityRecord)

            yield from page.items

            next_token = page.next_token
            if not next_token:
                break

    def detach_from_device(self, device_id: str) -> None:
        """Remove a Device from this Session's subjects.

        Args:
            device_id: ID of the Device to remove as a subject of this Session.
        """
        self.__roboto_client.delete(
            f"v1/sessions/id/{self.session_id}/devices",
            owner_org_id=self.org_id,
            data=DetachFromDeviceRequest(device_id=device_id),
        )

    def remove_file(self, file: typing.Union[File, str]) -> "Session":
        """Remove a single file's contributions from this Session.

        Thin convenience over :py:meth:`remove_files` for the common one-file case.

        Args:
            file: A :py:class:`~roboto.domain.files.File` or a raw file id.

        Returns:
            This Session, with recomputed aggregate bounds (``min_timestamp_ns`` / ``max_timestamp_ns``).
        """
        file_id = file.file_id if isinstance(file, File) else file
        return self.remove_files([file_id])

    def remove_files(self, file_ids: collections.abc.Sequence[str]) -> "Session":
        """Remove the given files' contributions from this Session.

        The service recomputes the Session's aggregate bounds across the remaining contributions,
        and the Session instance reflects the new ``min_timestamp_ns`` / ``max_timestamp_ns`` on return.

        Args:
            file_ids: File IDs whose contributions should be removed.

        Returns:
            This Session, with recomputed aggregate bounds (``min_timestamp_ns`` / ``max_timestamp_ns``).
        """
        record = self.__roboto_client.delete(
            f"v1/sessions/id/{self.session_id}/files",
            owner_org_id=self.org_id,
            data=RemoveFilesRequest(file_ids=list(file_ids)),
        ).to_record(SessionRecord)
        self.__record = record
        return self

    def update(
        self,
        name: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
    ) -> "Session":
        """Update mutable Session fields.

        Args:
            name: New name for the Session. Set to ``None`` to clear the name.
                Leave at the default to leave the name unchanged.

        Returns:
            This Session, refreshed from the server response.
        """
        request = remove_not_set(SessionUpdate(name=name))
        record = self.__roboto_client.put(
            f"v1/sessions/id/{self.session_id}",
            data=request,
            owner_org_id=self.org_id,
        ).to_record(SessionRecord)
        self.__record = record
        return self
