# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import datetime
import pathlib
import typing
import urllib.parse

from ...association import Association
from ...exceptions import (
    RobotoIllegalArgumentException,
    RobotoNotFoundException,
)
from ...experimental import topics as experimental_topics
from ...experimental.ingest import (
    DeclaredTimelineSource,
    FileTopicDeclaration,
    RepresentationDeclaration,
    Schema,
    TopicRepresentations,
)
from ...experimental.ingest.operations import DeclareTopicsRequest, SetRepresentationsRequest
from ...http import (
    BatchRequest,
    BatchResponse,
    RobotoClient,
)
from ...progress import (
    NoopProgressMonitor,
    TqdmProgressMonitor,
)
from ...query import QuerySpecification
from ...sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)
from ...storage import FileService
from ...time import Time, TimeUnit, to_epoch_nanoseconds
from ...updates import MetadataChangeset
from ...uri import RobotoUri
from ...warnings import experimental
from ..topics import (
    SetTimelineOffsetsRequest,
    TimelineExtentRecord,
    TimelineOffsetEntry,
    TimelineSourceRecord,
    Topic,
    TopicIdentityRecord,
)
from .operations import (
    ImportFileRequest,
    RenameFileRequest,
    UpdateFileRecordRequest,
)
from .record import FileRecord, IngestionStatus

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep


class File:
    """A file: a data item, such as a recording or report, uploaded or imported to a dataset, device, or organization.

    Common formats include ROS bags, MCAP, ULog, and CSV files. Ingestion extracts a file's data into topics, which
    ``get_topics`` lists, and ``ingestion_status`` records how far it has got. A file also carries tags and key-value
    metadata, and can be added to collections and processed by actions.

    Each change to a file, such as updating its metadata, renaming it, or uploading new content to its path, adds a
    version of it. Every version has the same ID.

    Get a ``File`` from ``from_id``, ``from_path_and_dataset_id``, ``query``, or ``import_one``. To wrap a
    :py:class:`~roboto.domain.files.FileRecord` already fetched from Roboto, build a ``File`` from it directly. Each
    instance holds a copy of one version of the file's record: methods that change the file, except ``rename_file``,
    update that copy from Roboto's response, and ``refresh`` fetches the latest version.

    Args:
        record: Record of one version of the file.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
        file_service: Transfers file contents to and from storage. Built from ``roboto_client`` if omitted.
    """

    __file_service: FileService
    __record: FileRecord
    __roboto_client: RobotoClient

    @classmethod
    def from_id(
        cls,
        file_id: str,
        version_id: typing.Optional[int] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> File:
        """Fetch a file by its ID.

        Args:
            file_id: ID of the file, beginning with ``fl_``.
            version_id: Version of the file to fetch. ``None`` fetches the latest version.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No file has this ID, the caller cannot see it, or it has no version
                ``version_id``.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> print(file.relative_path)

            Fetch the file's first version:

            >>> first_version = File.from_id("fl_12345", version_id=1)
            >>> print(first_version.version)
            1
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/files/record/{file_id}",
            query={"version_id": version_id} if version_id is not None else None,
        ).to_record(FileRecord)
        return cls(record, roboto_client)

    @classmethod
    def from_path_and_dataset_id(
        cls,
        file_path: typing.Union[str, pathlib.Path],
        dataset_id: str,
        version_id: typing.Optional[int] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> File:
        """Fetch one of a dataset's files by its path within the dataset.

        A file's path is unique within its dataset, so a path and a dataset identify one file.

        Args:
            file_path: Path of the file from the root of the dataset, such as ``logs/session1.bag``.
            dataset_id: ID of the dataset whose files include the file.
            version_id: Version of the file to fetch. ``None`` fetches the latest version.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: The dataset has no file at this path, the caller cannot see it, or the file has
                no version ``version_id``.

        Examples:
            >>> file = File.from_path_and_dataset_id("logs/session1.bag", "ds_12345")
            >>> print(file.file_id)

            Pass the path as a ``pathlib.Path``:

            >>> import pathlib
            >>> file = File.from_path_and_dataset_id(pathlib.Path("data/sensors.csv"), "ds_12345")
            >>> print(file.relative_path)
            data/sensors.csv
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        url_quoted_file_path = urllib.parse.quote(str(file_path), safe="")
        record = roboto_client.get(
            f"v1/files/record/path/{url_quoted_file_path}/association/{dataset_id}",
            query={"version_id": version_id} if version_id is not None else None,
        ).to_record(FileRecord)
        return cls(record, roboto_client)

    @classmethod
    def import_batch(
        cls,
        requests: collections.abc.Sequence[ImportFileRequest],
        roboto_client: typing.Optional[RobotoClient] = None,
        caller_org_id: typing.Optional[str] = None,
    ) -> collections.abc.Sequence[File]:
        """Import files that are already in bring-your-own buckets into datasets, without copying them.

        Each file's object stays in its bucket, which must be an S3 bucket registered with Roboto as a
        bring-your-own bucket of the caller's organization, read-only or read/write. Roboto stores only the file's
        record, so deleting the file from Roboto leaves the object in the bucket. All the files are imported in one
        request.

        Unlike ``import_one``, this method does not check that each object exists, and records the size each request
        states.

        Args:
            requests: One request per file to import, at most 500. Each must set ``size``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            caller_org_id: Organization to act in, which must own the buckets. Required when the caller belongs to
                more than one organization; otherwise the caller's only organization.

        Returns:
            The imported files.

        Raises:
            RobotoInvalidRequestException: A ``uri`` is not an ``s3://`` URI, a request has no ``size``, or there are
                more than 500 requests.
            RobotoNotFoundException: A bucket is not registered as a bring-your-own bucket of the caller's
                organization.

        Examples:
            >>> from roboto.domain.files import ImportFileRequest
            >>> requests = [
            ...     ImportFileRequest(
            ...         dataset_id="ds_12345",
            ...         relative_path="logs/session1.bag",
            ...         uri="s3://my-bucket/data/session1.bag",
            ...         size=1024000,
            ...     ),
            ...     ImportFileRequest(
            ...         dataset_id="ds_12345",
            ...         relative_path="logs/session2.bag",
            ...         uri="s3://my-bucket/data/session2.bag",
            ...         size=2048000,
            ...     ),
            ... ]
            >>> files = File.import_batch(requests)
            >>> print(f"Imported {len(files)} files")
            Imported 2 files
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        # Pydantic does not serialize every collections.abc.Sequence correctly, so pass it a list.
        request: BatchRequest[ImportFileRequest] = BatchRequest(requests=list(requests))

        records = roboto_client.post(
            "v1/files/import/batch",
            data=request,
            idempotent=True,
            caller_org_id=caller_org_id,
        ).to_record_list(FileRecord)
        return [cls(record, roboto_client) for record in records]

    @classmethod
    def import_one(
        cls,
        dataset_id: str,
        relative_path: str,
        uri: str,
        description: typing.Optional[str] = None,
        tags: typing.Optional[list[str]] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        device_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> File:
        """Import one file that is already in a bring-your-own bucket into a dataset, without copying it.

        The file's object stays in its bucket, which must be an S3 bucket registered with Roboto as a
        bring-your-own bucket of the caller's organization. Roboto stores only the file's record, so deleting the
        file from Roboto leaves the object in the bucket.

        Unlike ``import_batch``, this method reads the object's size from the bucket, which also checks that the
        object exists. If the dataset already has a file at ``relative_path``
        with the same ``uri`` and size, that file is returned and nothing is imported.

        Args:
            dataset_id: ID of the dataset to import the file into.
            relative_path: Path of the file within the dataset, such as ``logs/session1.bag``.
            uri: Storage URI of the object, such as ``s3://my-bucket/path/to/file.bag``.
            description: Human-readable description of the file.
            tags: Tags to set on the file. ``None`` sets none.
            metadata: Key-value metadata to set on the file. ``None`` sets none.
            device_id: ID of the device the file's data came from. ``None`` records none.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The imported file.

        Raises:
            RobotoInvalidRequestException: ``uri`` is not an ``s3://`` URI.
            RobotoNotFoundException: The bucket is not registered as a bring-your-own bucket of the caller's
                organization, or holds no object at ``uri``.
            RobotoUnauthorizedException: Roboto cannot read the object with the access the organization granted it,
                which S3 can also report for a missing object.

        Examples:
            Import a ROS bag:

            >>> from roboto.domain.files import File
            >>> file = File.import_one(
            ...     dataset_id="ds_12345", relative_path="logs/session1.bag", uri="s3://my-bucket/data/session1.bag"
            ... )
            >>> print(f"Imported file: {file.relative_path}")
            Imported file: logs/session1.bag

            Import a file with a description, tags, and metadata:

            >>> file = File.import_one(
            ...     dataset_id="ds_12345",
            ...     relative_path="sensors/lidar_data.pcd",
            ...     uri="s3://my-bucket/sensors/lidar_data.pcd",
            ...     description="LiDAR point cloud from highway test",
            ...     tags=["lidar", "highway", "test"],
            ...     metadata={"sensor_type": "Velodyne", "resolution": "high"},
            ... )
            >>> print(f"File size: {file.record.size} bytes")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = ImportFileRequest(
            dataset_id=dataset_id,
            relative_path=relative_path,
            uri=uri,
            description=description,
            tags=tags,
            metadata=metadata,
            device_id=device_id,
        )
        record = roboto_client.post("v1/files/import", data=request).to_record(FileRecord)
        return cls(record, roboto_client)

    @classmethod
    def query(
        cls,
        spec: typing.Optional[QuerySpecification] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        owner_org_id: typing.Optional[str] = None,
    ) -> collections.abc.Generator[File, None, None]:
        """Yield the files that match a query, fetching them a page at a time.

        Args:
            spec: Conditions, sort order, and page size of the query. ``None`` matches every file in the
                organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            owner_org_id: Organization whose files to search. Defaults to the organization the caller acts in.

        Raises:
            ValueError: A condition in ``spec`` names a field that :py:class:`~roboto.domain.files.FileRecord` does
                not have. Only the first part of a dotted field, such as ``metadata.vehicle_id``, is checked. It
                surfaces on the first iteration, before any request is made.

        Note:
            Paging sets ``spec.after``, so a ``spec`` passed to a second query starts at the last page the first one
            fetched rather than at the first page.

        Examples:
            Print the path of every file tagged ``sensor-data``:

            >>> from roboto.query import Comparator, Condition, QuerySpecification
            >>> spec = QuerySpecification(
            ...     condition=Condition(field="tags", comparator=Comparator.Contains, value="sensor-data")
            ... )
            >>> for file in File.query(spec):
            ...     print(file.relative_path)

            Count the files whose metadata names one vehicle:

            >>> spec = QuerySpecification(
            ...     condition=Condition(field="metadata.vehicle_id", comparator=Comparator.Equals, value="vehicle_001")
            ... )
            >>> files = list(File.query(spec))
            >>> print(f"Found {len(files)} files for vehicle_001")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        spec = spec or QuerySpecification()

        known = set(FileRecord.model_fields.keys())
        actual = set()
        for field in spec.fields():
            # Check a dotted field, such as "metadata.SoftwareVersion", by its top-level field alone.
            if "." in field:
                actual.add(field.split(".")[0])
            else:
                actual.add(field)
        unknown = actual - known
        if unknown:
            plural = len(unknown) > 1
            msg = "are not known attributes of File" if plural else "is not a known attribute of File"
            raise ValueError(f"{unknown} {msg}. Known attributes: {known}")

        while True:
            paginated_results = roboto_client.post(
                "v1/files/query", data=spec, owner_org_id=owner_org_id, idempotent=True
            ).to_paginated_list(FileRecord)

            for record in paginated_results.items:
                yield cls(record, roboto_client)

            if paginated_results.next_token:
                spec.after = paginated_results.next_token
            else:
                break

    def __init__(
        self,
        record: FileRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
        file_service: typing.Optional[FileService] = None,
    ):
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__file_service = file_service or FileService(self.__roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def created(self) -> datetime.datetime:
        """Time the file was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Principal that created the file, as ``<type>:<id>``, such as ``user:<user_id>``.

        A file an action wrote has ``invocation:<invocation_id>``.
        """
        return self.__record.created_by

    @property
    def association(self) -> Association:
        """Dataset, device, device type, or organization whose files include this file.

        Every file has exactly one. Read ``file.association.association_type`` to tell which kind it is.
        """
        return Association.from_id(self.__record.association_id)

    @property
    def dataset_id(self) -> str:
        """ID of the dataset whose files include this file.

        A device's, a device type's, or an organization's files have no dataset. Prefer ``association``, which works
        for every file. Reading it raises ``RobotoIllegalArgumentException`` when the file is not associated with a
        dataset.
        """
        association = self.association
        if not association.is_dataset:
            raise RobotoIllegalArgumentException(
                f"File {self.file_id} is not in a dataset; its association is "
                f"{association.association_type.value} {association.association_id}. Use File.association instead."
            )
        return association.association_id

    @property
    def description(self) -> typing.Optional[str]:
        """Human-readable description of the file, or ``None`` if it has none."""
        return self.__record.description

    @property
    def device_id(self) -> typing.Optional[str]:
        """ID of the device the file's data came from, or ``None`` if none was given."""
        return self.__record.device_id

    @property
    def file_id(self) -> str:
        """Unique ID of the file, beginning with ``fl_``. Every version of the file has the same ID."""
        return self.__record.file_id

    @property
    def ingestion_status(self) -> IngestionStatus:
        """How much of the file's data has been ingested into topics."""
        return self.__record.ingestion_status

    @property
    def is_link(self) -> bool:
        """Whether this file is a link to one version of another file.

        A link has its own path among a device's, a device type's, or an organization's files, and stores no object.
        ``download`` and ``get_signed_url`` fetch the target at the version the link pins.
        """
        return self.__record.is_link

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the file."""
        return self.__record.org_id

    @property
    def record(self) -> FileRecord:
        """Record of the file that this instance holds."""
        return self.__record

    @property
    def relative_path(self) -> str:
        """Path of the file from the root of its dataset's, device's, or organization's files, with forward slashes.

        :py:attr:`~roboto.domain.files.FileRecord.relative_path` says whether paths must be unique and where a download
        writes the file.
        """
        return self.__record.relative_path

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Key-value metadata on the file."""
        return self.__record.metadata

    @property
    def modified(self) -> datetime.datetime:
        """Time the file was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Principal that last modified the file, in the same ``<type>:<id>`` form as ``created_by``."""
        return self.__record.modified_by

    @property
    def tags(self) -> list[str]:
        """Tags on the file."""
        return self.__record.tags

    @property
    def uri(self) -> str:
        """Location of the object that holds the file's content, such as ``s3://<bucket>/<key>``.

        :py:attr:`~roboto.domain.files.FileRecord.uri` says what it holds on a link.
        """
        return self.__record.uri

    @property
    def version(self) -> int:
        """Version of the file, starting at 1.

        :py:attr:`~roboto.domain.files.FileRecord.version` says which changes add a version.
        """
        return self.__record.version

    def add_topic(
        self,
        topic_name: str,
        df: "pandas.DataFrame",
        timestamp_column: typing.Optional[str] = None,
        timestamp_unit: typing.Optional[typing.Union[str, TimeUnit]] = None,
    ) -> Topic:
        """Create a topic of this file from a pandas DataFrame.

        Roboto infers the topic's message paths from the DataFrame's columns, stores the DataFrame as a Parquet file
        among the dataset's files, and reads the topic's data from it. If the file already has a topic named
        ``topic_name``, its message paths, time range, and data are replaced with the DataFrame's.

        Requires the ``roboto[ingestion]`` extra.

        Args:
            topic_name: Name of the topic. Topic names are unique within a file.
            df: Data of the topic, one message per row, including a column of timestamps.
            timestamp_column: Name of the column that holds each row's timestamp. ``None`` uses the first column
                whose type is a timezone-aware timestamp.
            timestamp_unit: Unit of the values in ``timestamp_column``, such as ``"s"``, ``"ms"``, ``"us"``, or
                ``"ns"``. Required when that column holds numbers; not needed for a column of datetimes.

        Returns:
            The created or updated topic.

        Raises:
            IngestionException: No timestamp column can be found, ``timestamp_column`` is not in ``df`` or has a type
                that cannot hold timestamps, or ``timestamp_unit`` is missing for a numeric column.
            ImportError: The ``roboto[ingestion]`` extra is not installed.
            RobotoIllegalArgumentException: This file is among a device's, a device type's, or an organization's
                files, not a dataset's; only a dataset's files hold topics.

        Examples:
            Create a topic with an explicit timestamp column and unit:

            >>> import pandas as pd
            >>> from roboto import File
            >>> file = File.from_id("fl_12345")
            >>> df = pd.DataFrame(
            ...     {
            ...         "timestamp": [1763947309.4198897, 1763947316.7686195, 1763947335.0095527],
            ...         "temperature": [20.5, 21.0, 20.8],
            ...         "humidity": [45.2, 46.1, 45.8],
            ...     }
            ... )
            >>> topic = file.add_topic(
            ...     topic_name="sensor_data", df=df, timestamp_column="timestamp", timestamp_unit="s"
            ... )
            >>> print(f"Created topic: {topic.name}")
            Created topic: sensor_data

            Create a topic whose timestamp column is found automatically:

            >>> import pandas as pd
            >>> from roboto import File
            >>> file = File.from_id("fl_12345")
            >>> df = pd.DataFrame(
            ...     {
            ...         "ts": pd.date_range("2025-11-24", periods=3, freq="1s", tz="UTC"),
            ...         "velocity": [10.5, 11.2, 10.8],
            ...         "acceleration": [0.5, 0.3, -0.2],
            ...     }
            ... )
            >>> topic = file.add_topic("motion_data", df)

            Read the data back:

            >>> retrieved_df = topic.get_data_as_df()
            >>> print(f"Retrieved {len(retrieved_df)} rows")
            Retrieved 3 rows

            Add derived data as a new topic to the same file, using the original topic's timestamp index:

            >>> import pandas as pd
            >>> from roboto import File
            >>> file = File.from_id("fl_12345")
            >>> original_topic = file.get_topic("sensor_data")
            >>> original_df = original_topic.get_data_as_df()
            >>> derived_df = pd.DataFrame(
            ...     {
            ...         "temp_category": original_df["temperature"].apply(lambda x: "hot" if x > 25 else "not_hot"),
            ...     },
            ...     index=original_df.index,
            ... )
            >>> derived_topic = file.add_topic(
            ...     "temperature_categories",
            ...     derived_df,
            ... )
        """
        association = self.association
        if not association.is_dataset:
            raise RobotoIllegalArgumentException(
                f"File {self.file_id} is not in a dataset, so it cannot hold topics; its association is "
                f"{association.association_type.value} {association.association_id}."
            )
        return Topic.create_from_df(
            self.file_id,
            association.association_id,
            topic_name,
            df,
            timestamp_column=timestamp_column,
            timestamp_unit=timestamp_unit,
            caller_org_id=self.org_id,
            roboto_client=self.__roboto_client,
        )

    @experimental
    def declare_topic(
        self,
        topic_name: str,
        topic_schema: Schema,
        timeline_sources: collections.abc.Sequence[DeclaredTimelineSource],
        data_range: typing.Optional[tuple[int, int]] = None,
        anchor: typing.Optional[Time] = None,
        representations: collections.abc.Sequence[RepresentationDeclaration] = (),
    ) -> experimental_topics.Topic:
        """Register one topic whose data this file carries, without naming a session.

        The single-topic form of ``File.declare_topics``, taking the fields of one
        ``roboto.experimental.ingest.FileTopicDeclaration`` as separate arguments. That class documents what each field
        means, and ``File.declare_topics`` documents what Roboto does with them. The failures of
        ``File.declare_topics`` also apply.

        Args:
            topic_name: Name of the topic whose data this file carries. Topic names are unique within an
                organization.
            topic_schema: Structure of the topic's data.
            timeline_sources: Timeline sources the topic's data carries, each with the bounds it spans in this file,
                in the file's own timestamps.
            data_range: Part of the file the topic's data occupies. ``None`` is the whole file.
            anchor: Wall-clock instant the declared data was captured at: an ``int`` of nanoseconds since the Unix
                epoch, or any other :py:const:`~roboto.time.Time`, read as :py:func:`~roboto.time.to_epoch_nanoseconds`
                reads it (a ``datetime`` or ISO 8601 string is that instant; a ``float``, ``Decimal``, or numeric
                string is seconds since the epoch). Must fall after the Unix epoch. ``None`` keeps the anchor an
                earlier declaration gave the data, if any.
            representations: Files a read of the topic's data opens, each with how it holds that data: this file,
                when its own bytes are readable, and other files the data is read from, such as files converted from
                it. An empty sequence lists none, and reads of a topic with no representations return no rows.

        Returns:
            The registered topic.

        Raises:
            TypeError: ``anchor`` is not one of the :py:const:`~roboto.time.Time` types.
            ValueError: ``anchor`` is a boolean, a negative number (an ``int``, ``float``, ``Decimal``, or numeric
                string), or a string that is neither a number of seconds nor an ISO 8601 timestamp. Raised before any
                request is made.
            OverflowError: ``anchor`` is an infinite ``float``, ``Decimal``, or string, such as ``"inf"``. Raised
                before any request is made.
            pydantic.ValidationError: The arguments do not form a valid ``FileTopicDeclaration``: for instance, two
                representations of the whole topic, or of one field, share a storage format, content format, and
                transformations; a timeline source other than ``SchemaFieldSource`` is given with a
                :py:attr:`~roboto.domain.topics.RepresentationStorageFormat.PARQUET` representation; or
                ``representations`` names one file in two storage formats. Raised before any request is made.
            RobotoDomainException: Roboto refused the declaration. The exception raised is the one Roboto refused it
                with, such as ``RobotoNotFoundException``.

        Examples:
            >>> from roboto.domain.files import File
            >>> from roboto.domain.topics import CanonicalDataType, RepresentationStorageFormat
            >>> from roboto.experimental.ingest import Field, RepresentationDeclaration, Schema, SchemaFieldSource
            >>> timestamp = Field(
            ...     name="timestamp",
            ...     data_type="float64",
            ...     canonical_data_type=CanonicalDataType.Timestamp,
            ...     unit="s",
            ... )
            >>> file = File.from_id("fl_12345")
            >>> topic = file.declare_topic(
            ...     topic_name="observation.state",
            ...     topic_schema=Schema(
            ...         name="observation.state",
            ...         fields=[timestamp, Field(name="observation.state", data_type="float32")],
            ...     ),
            ...     timeline_sources=[
            ...         SchemaFieldSource(
            ...             field_path=["timestamp"],
            ...             min_file_timestamp_ns=0,
            ...             max_file_timestamp_ns=4_000,
            ...         )
            ...     ],
            ...     representations=[
            ...         RepresentationDeclaration(
            ...             file_id=file.file_id,
            ...             storage_format=RepresentationStorageFormat.PARQUET,
            ...         )
            ...     ],
            ... )
            >>> print(topic.topic_id)
        """
        declaration = FileTopicDeclaration(
            topic_name=topic_name,
            topic_schema=topic_schema,
            timeline_sources=list(timeline_sources),
            data_range=data_range,
            anchor_ns=None if anchor is None else to_epoch_nanoseconds(anchor),
            representations=list(representations),
        )
        return self.declare_topics([declaration]).single()

    @experimental
    def declare_topics(
        self,
        topics: collections.abc.Sequence[FileTopicDeclaration],
    ) -> BatchResponse[experimental_topics.Topic]:
        """Register the topic data this file carries, without naming a session.

        One call states everything Roboto needs to serve this file's topic data: for each topic, the structure of
        its rows, the timeline sources those rows carry with the bounds they span in this file, and, when the file
        packs its data into slices, which slice the topic occupies. Roboto does not open the file when topics are
        declared on it, so the declarations are all it knows about the file's contents.

        Roboto applies each declaration on its own: one it refuses leaves the others registered, and the response
        says what became of each. No session is involved, so declarations on the files of one recording can run
        concurrently, and a file's topic data can be registered before the session that holds it exists. A session
        takes the data on when the file is added to it, through ``roboto.experimental.sessions.Session.add_file`` or a
        ``SessionFile`` carrying no topics. A session that already holds the file takes on what this call declares
        before the call returns, with its time bounds recomputed to cover the newly declared data.

        Resending the same call is safe. Roboto identifies the data a declaration registers by the topic and the
        slice of the file the declaration names, so a resend finds what the first attempt registered instead of
        registering it twice, and a corrected redeclaration replaces what it corrects.

        A declaration states its bounds in the file's own timestamps, read as nanoseconds since the Unix epoch;
        Roboto never assigns a wall-clock time. Data whose timestamps start at 0 therefore sits at the epoch until it
        is anchored. To place it at the wall-clock time it was captured, set
        ``roboto.experimental.ingest.FileTopicDeclaration.anchor_ns``. An anchor applies to the whole slice it names,
        not only to the topic declaring it, so the topics sharing a slice must agree on it.

        The topic data belongs to this file: its bounds, anchors, and slices are stated against it, and a session
        holding this file holds the data. Each topic's ``TopicDeclaration.representations`` make the data readable:
        they name the files a read opens to get it, each decoded in the storage format its representation states,
        whatever the file's name and extension. A topic lists this file when its own bytes are readable, and other
        files when the data is read from them, such as the per-topic MCAP files converted from a PX4 ULog. A topic
        with no representations is still registered and still counts toward the time bounds of the sessions holding
        the file, but reads of it return no rows. ``RepresentationDeclaration`` states what a representation's file
        must hold and when a read can decode an :py:attr:`~roboto.domain.topics.RepresentationStorageFormat.MCAP`
        representation's file.

        Redeclaring a topic adds the listed representations to the ones it has, each replacing the stored ones it
        matches, as ``TopicDeclaration.representations`` describes. To remove a representation, or to replace a
        topic's representations outright, use ``File.set_representations``.

        Args:
            topics: One declaration per topic and slice of this file. An empty sequence returns an empty response
                without making a request.

        Returns:
            One element per declaration, in request order, holding either the topic it registered or why Roboto
            refused it.

        Raises:
            pydantic.ValidationError: More than 500 declarations are given
                (``roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST``), one topic is declared twice over
                the same slice, two declarations anchor one slice at different instants, or representations name one
                file in two storage formats. Raised before any request is made; each declaration's own rules are
                checked earlier, when it is built.
            RobotoNotFoundException: This file no longer exists, or a representation names a file that is not in
                this file's organization or whose status is not :py:attr:`~roboto.domain.files.FileStatus.Available`.
                Nothing is registered.
            RobotoUnauthorizedException: The caller cannot edit this file or a file a representation names, or a
                declaration sets ``is_default_for_reads`` on a timeline source and the caller cannot edit topics in
                this file's organization.

        Examples:
            Register the two topics a LeRobot episode file carries, each read from the file's own bytes:

            >>> from roboto.domain.files import File
            >>> from roboto.domain.topics import CanonicalDataType, RepresentationStorageFormat
            >>> from roboto.experimental.ingest import (
            ...     Field,
            ...     FileTopicDeclaration,
            ...     RepresentationDeclaration,
            ...     Schema,
            ...     SchemaFieldSource,
            ... )
            >>> timestamp = Field(
            ...     name="timestamp",
            ...     data_type="float64",
            ...     canonical_data_type=CanonicalDataType.Timestamp,
            ...     unit="s",
            ... )
            >>> file = File.from_id("fl_12345")
            >>> from_file = RepresentationDeclaration(
            ...     file_id=file.file_id,
            ...     storage_format=RepresentationStorageFormat.PARQUET,
            ... )
            >>> registered = file.declare_topics(
            ...     [
            ...         FileTopicDeclaration(
            ...             topic_name="observation.state",
            ...             topic_schema=Schema(
            ...                 name="observation.state",
            ...                 fields=[timestamp, Field(name="observation.state", data_type="float32")],
            ...             ),
            ...             timeline_sources=[
            ...                 SchemaFieldSource(
            ...                     field_path=["timestamp"],
            ...                     min_file_timestamp_ns=0,
            ...                     max_file_timestamp_ns=4_000,
            ...                 )
            ...             ],
            ...             representations=[from_file],
            ...         ),
            ...         FileTopicDeclaration(
            ...             topic_name="action",
            ...             topic_schema=Schema(
            ...                 name="action",
            ...                 fields=[timestamp, Field(name="action", data_type="float32")],
            ...             ),
            ...             timeline_sources=[
            ...                 SchemaFieldSource(
            ...                     field_path=["timestamp"],
            ...                     min_file_timestamp_ns=0,
            ...                     max_file_timestamp_ns=4_000,
            ...                 )
            ...             ],
            ...             representations=[from_file],
            ...         ),
            ...     ],
            ... )
            >>> print([topic.topic_id for topic in registered.succeeded])

            Register a topic over the slice of a shared file that holds one episode, anchored at the
            instant that episode was recorded:

            >>> registered = file.declare_topics(
            ...     [
            ...         FileTopicDeclaration(
            ...             topic_name="observation.state",
            ...             topic_schema=Schema(
            ...                 name="observation.state",
            ...                 fields=[timestamp, Field(name="observation.state", data_type="float32")],
            ...             ),
            ...             timeline_sources=[
            ...                 SchemaFieldSource(
            ...                     field_path=["timestamp"],
            ...                     min_file_timestamp_ns=0,
            ...                     max_file_timestamp_ns=4_000,
            ...                 )
            ...             ],
            ...             data_range=(0, 80),
            ...             anchor_ns=1_785_974_400_000_000_000,
            ...             representations=[from_file],
            ...         ),
            ...     ],
            ... )
        """
        if not topics:
            return BatchResponse[experimental_topics.Topic](responses=[])

        registered = self.__roboto_client.post(
            f"v1/files/id/{self.file_id}/topics",
            data=DeclareTopicsRequest(topics=list(topics)),
        ).to_record(BatchResponse[TopicIdentityRecord])
        return registered.map_data(
            lambda record: experimental_topics.Topic.from_record(record, roboto_client=self.__roboto_client)
        )

    def delete(self) -> None:
        """Delete every version of this file, with its topics and everything else derived from it.

        The deletion cannot be undone. For a file uploaded through Roboto, the object holding each version's content
        is deleted too, whether it is in a Roboto-managed bucket or a bring-your-own bucket. A file imported from a
        bring-your-own bucket, by ``import_batch`` or ``import_one``, keeps its object in the bucket. Deleting a link
        leaves its target in place.

        Raises:
            RobotoNotFoundException: The file does not exist or has already been deleted.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> file.delete()
        """
        self.__roboto_client.delete(f"/v1/files/{self.file_id}")

    def download(
        self,
        local_path: pathlib.Path,
        print_progress: bool = True,
    ):
        """Download this file's content to a local path.

        Downloads the version of the file this instance holds, or, for a link, the target file at the version the
        link pins. Creates the parent directories of ``local_path`` that do not exist, and makes up to three attempts.

        Args:
            local_path: Path to write the file to, including its name.
            print_progress: Whether to show a progress bar while downloading.

        Raises:
            RobotoNotFoundException: This file is a link whose target, at the pinned version, no longer exists.
            RobotoUnauthorizedException: This file is a link, and the caller cannot read its target.
            ExceptionGroup: All three attempts failed. The group holds the last attempt's error.

        Examples:
            >>> import pathlib
            >>> file = File.from_id("fl_12345")
            >>> local_path = pathlib.Path("/tmp/downloaded_file.bag")
            >>> file.download(local_path)
            >>> print(f"Downloaded to {local_path}")
        """
        source = self._resolve_link()
        progress_monitor = (
            TqdmProgressMonitor(
                total=source.record.size,
                desc=f"Downloading {self.relative_path}",
            )
            if print_progress
            else NoopProgressMonitor()
        )

        with progress_monitor:
            self.__file_service.download(
                files=[
                    {
                        "bucket_name": source.record.bucket,
                        "source_uri": source.record.uri,
                        "destination_path": local_path,
                    }
                ],
                # The object lives under the source's association, so read credentials for it come from there.
                association=source.association,
                caller_org_id=source.org_id,
                on_progress=progress_monitor.update,
            )

    def get_signed_url(
        self,
        override_content_type: typing.Optional[str] = None,
        override_content_disposition: typing.Optional[str] = None,
    ) -> str:
        """Fetch a signed URL that downloads this file's content without Roboto credentials.

        The URL works for one hour after it is issued. It downloads the file's latest version, even when this
        instance holds an earlier one. For a link, it downloads the target file at the version the link pins.

        Args:
            override_content_type: MIME type for the URL's response to declare in its ``Content-Type`` header.
                ``None`` uses the object's stored type.
            override_content_disposition: Value for the URL's response's ``Content-Disposition`` header, such as
                ``"attachment; filename=myfile.bag"``. ``None`` uses the object's stored value.

        Raises:
            RobotoNotFoundException: This file is a link whose target, at the pinned version, no longer exists.
            RobotoUnauthorizedException: This file is a link, and the caller cannot read its target.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> url = file.get_signed_url()
            >>> print(url)

            Have a browser save the file as ``data.bag`` instead of displaying it:

            >>> download_url = file.get_signed_url(override_content_disposition="attachment; filename=data.bag")
        """
        query_params: dict[str, str] = {}

        if override_content_disposition:
            query_params["override_content_disposition"] = override_content_disposition

        if override_content_type:
            query_params["override_content_type"] = override_content_type

        source = self._resolve_link()
        if source is not self:
            query_params["version_id"] = str(source.version)

        res = self.__roboto_client.get(
            f"v1/files/{source.file_id}/signed-url",
            query=query_params,
            owner_org_id=source.org_id,
        )
        return res.to_dict(json_path=["data", "url"])

    def get_topic(self, topic_name: str) -> Topic:
        """Fetch one of this file's topics by name.

        Calls :py:meth:`~roboto.domain.topics.Topic.from_name_and_file`, whose failures also apply.

        Args:
            topic_name: Name of the topic, such as ``"/imu/data"``. Topic names are unique within a file.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> topic = file.get_topic("/imu/data")
            >>> print(topic.schema_name)

            Print the topic's messages:

            >>> for timestamp, message in topic.get_data():
            ...     print(timestamp, message)
        """
        return Topic.from_name_and_file(
            topic_name=topic_name,
            file_id=self.file_id,
            owner_org_id=self.org_id,
            roboto_client=self.__roboto_client,
        )

    def get_topics(
        self,
        include: typing.Optional[collections.abc.Sequence[str]] = None,
        exclude: typing.Optional[collections.abc.Sequence[str]] = None,
    ) -> collections.abc.Generator["Topic", None, None]:
        """Yield this file's topics, optionally only those with some names.

        Args:
            include: Names of the topics to yield. ``None`` yields every topic not in ``exclude``.
            exclude: Names of the topics to leave out. ``None`` leaves out none.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> for topic in file.get_topics():
            ...     print(topic.name)

            Yield only two camera topics:

            >>> camera_topics = list(file.get_topics(include=["/camera/image", "/camera/info"]))

            Leave out the diagnostics topic:

            >>> data_topics = list(file.get_topics(exclude=["/diagnostics"]))
        """
        for topic in Topic.get_by_file(
            owner_org_id=self.org_id,
            file_id=self.file_id,
            roboto_client=self.__roboto_client,
        ):
            if include is not None and topic.name not in include:
                continue

            if exclude is not None and topic.name in exclude:
                continue

            yield topic

    def mark_ingested(self) -> File:
        """Mark this file as fully ingested.

        A custom ingestion action calls this on each file it finishes, because triggers that run when a file
        finishes ingestion act only on files marked ingested. Calls ``update`` with ``ingestion_complete=True``, whose
        failures also apply.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> file = file.mark_ingested()
            >>> print(file.ingestion_status)
            ingested
        """
        return self.update(ingestion_complete=True)

    def put_metadata(self, metadata: dict[str, typing.Any]) -> File:
        """Add keys to this file's metadata, or change the values of keys it has.

        Keys not in ``metadata`` keep their values. Calls ``update``, whose failures also apply.

        Args:
            metadata: Key-value metadata to set on the file.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> file = file.put_metadata({"vehicle_id": "vehicle_001", "session_type": "highway_driving"})
            >>> print(file.metadata["vehicle_id"])
            vehicle_001
        """
        return self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(self, tags: list[str]) -> File:
        """Add tags to this file.

        Keeps the file's existing tags. A tag the file already has is not added again. Calls ``update``, whose
        failures also apply.

        Args:
            tags: Tags to add to the file.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> file = file.put_tags(["sensor-data", "highway"])
            >>> file = file.put_tags(["sunny"])
            >>> {"sensor-data", "highway", "sunny"} <= set(file.tags)
            True
        """
        return self.update(metadata_changeset=MetadataChangeset(put_tags=tags))

    def refresh(self) -> File:
        """Fetch the latest version of this file's record from Roboto, to see changes made elsewhere.

        The instance then holds the latest version, even if it held an earlier one.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoNotFoundException: The file no longer exists.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> file = file.refresh()
            >>> print(file.version)
        """
        self.__record = self.__roboto_client.get(f"v1/files/record/{self.file_id}").to_record(FileRecord)
        return self

    def rename_file(self, file_id: str, new_path: str) -> FileRecord:
        """Move this file to another path among its dataset's, device's, or organization's files.

        The file keeps its ID, and the move adds a version of it. Its content is not copied. This instance keeps the
        record it held; the method returns the new one.

        Args:
            file_id: Ignored. The method moves this file whatever ID is passed.
            new_path: Path to move the file to, relative to the root of its dataset's, device's, or organization's
                files. The directory at its parent path must already exist.

        Returns:
            Record of the file's new version, at ``new_path``.

        Raises:
            RobotoInvalidRequestException: No directory exists at the parent path of ``new_path``, or something there
                already has the new name.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> record = file.rename_file(file.file_id, "logs/session1.bag")
            >>> print(record.relative_path)
            logs/session1.bag
        """
        response = self.__roboto_client.put(
            f"v1/files/{self.file_id}/rename",
            data=RenameFileRequest(
                association_id=self.__record.association_id,
                new_path=new_path,
            ),
        )

        return response.to_record(FileRecord)

    def set_device_id(self, device_id: str) -> File:
        """Set the device this file's data came from.

        Calls ``update``, whose failures also apply.

        Args:
            device_id: ID of the device.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> file = file.set_device_id("robot_001")
        """
        return self.update(device_id=device_id)

    @experimental
    def set_representations(self, topics: collections.abc.Sequence[TopicRepresentations]) -> None:
        """Replace the representations that the named topics' data on this file is read from.

        This file is the one the topics were declared on, through ``File.declare_topics`` or a session. Each listed
        topic ends up with exactly the listed representations over the part of this file its entry's ``data_range``
        names; its other representations there are removed, whether they cover the whole topic or one field of it.
        Topics and slices not listed keep theirs. Nothing else about the topics changes: their schemas, timeline
        sources, bounds, anchors, and slices stay as declared, and so do the time bounds of every session holding this
        file, which do not depend on which files the data is read from.

        Use it for what redeclaring a topic cannot do:

        1. Remove a representation.
        2. Replace a representation with one that names another file and differs from it in what it covers, its
           storage format, its content format, or its transformations. Those four identify a representation, as
           ``roboto.experimental.ingest.RepresentationDeclaration`` describes, so declaring the new one adds it beside
           the first.
        3. Stop a topic being read at all, by listing no representations for it.

        Roboto checks every entry before writing any, and one refused entry refuses the whole call.

        Args:
            topics: One entry per topic and slice, at most 500
                (``roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST``); split a larger set across several
                calls. An empty sequence returns without making a request.

        Raises:
            pydantic.ValidationError: ``topics`` has more entries than the limit, lists one topic and slice twice, or
                lists representations naming one file in two storage formats. Raised before any request is made.
                The rules for one topic's own representations are checked earlier, when its
                ``TopicRepresentations`` is built.
            RobotoNotFoundException: This file does not exist, a topic is not declared on it, an entry's
                ``data_range`` is not one the topic is declared over on it, or a representation names a file that is
                not in this file's organization or whose status is not
                :py:attr:`~roboto.domain.files.FileStatus.Available`. Nothing is written.
            RobotoInvalidRequestException: A topic declared with a timeline source other than ``SchemaFieldSource``
                (MCAP log or publish time, MP4 presentation time) would get a
                :py:attr:`~roboto.domain.topics.RepresentationStorageFormat.PARQUET` representation, a topic
                declared over a ``data_range`` would be left with a representation that cannot be read by row position
                and none that can covering the same fields, as ``RepresentationDeclaration.transformations``
                describes, or a representation's ``field_path`` names no field of the schema the topic is declared
                under on this file. Nothing is written.
            RobotoUnauthorizedException: The caller cannot edit this file or a file a listed representation names.

        Examples:
            Replace a camera topic's representation re-encoded as JPEG with one downsampled and re-encoded as
            PNG, keeping the untransformed one that names the recording, and stop reading a debug topic at all:

            >>> from roboto.domain.files import File
            >>> from roboto.domain.topics import RepresentationStorageFormat
            >>> from roboto.experimental.ingest import RepresentationDeclaration, TopicRepresentations
            >>> recording = File.from_id("fl_12345")
            >>> recording.set_representations(
            ...     [
            ...         TopicRepresentations(
            ...             topic_name="/camera/front/image_raw",
            ...             representations=[
            ...                 RepresentationDeclaration(
            ...                     file_id=recording.file_id,
            ...                     storage_format=RepresentationStorageFormat.MCAP,
            ...                 ),
            ...                 RepresentationDeclaration(
            ...                     file_id="fl_67890",
            ...                     storage_format=RepresentationStorageFormat.MCAP,
            ...                     content_format="png",
            ...                     transformations=["downsample:0.5", "encode:png"],
            ...                 ),
            ...             ],
            ...         ),
            ...         TopicRepresentations(topic_name="/debug/raw_dump", representations=[]),
            ...     ]
            ... )
        """
        if not topics:
            return

        self.__roboto_client.put(
            f"v1/files/id/{self.file_id}/representations",
            data=SetRepresentationsRequest(topics=list(topics)),
        )

    @experimental
    def set_timeline_offset(
        self,
        offset: Time,
        *,
        topic: typing.Optional[Topic] = None,
        topic_name: typing.Optional[str] = None,
        timeline_source: typing.Optional[TimelineSourceRecord] = None,
        timeline_source_name: typing.Optional[str] = None,
    ) -> list[TimelineExtentRecord]:
        """Set the offset that converts this file's stored timestamps to Unix-epoch time, for some or all of its topics.

        Roboto adds the offset, in nanoseconds, to each stored timestamp it reaches:
        ``unix_epoch_time_ns = stored_time_ns + offset_ns``. An offset given as an instant, such as a ``datetime``, is
        the instant at which stored time 0 occurred. With no selector, the offset applies to every timeline on the
        file. ``topic`` or ``topic_name`` limits it to one topic; ``timeline_source`` limits it to one timeline
        source, and ``timeline_source_name`` to the timeline sources of that name.

        Use ``File.set_timeline_offsets`` to apply several offsets in one request, all or none of them. This method
        calls it, so its failures also apply.

        Args:
            offset: Offset to apply: an ``int`` of nanoseconds, or any other :py:const:`~roboto.time.Time`, read as
                :py:func:`~roboto.time.to_epoch_nanoseconds` reads it (a ``datetime`` or ISO 8601 string is that
                instant; a ``float``, ``Decimal``, or numeric string is seconds). Must not be negative, and must fit in
                a signed 64-bit integer of nanoseconds.
            topic: Topic to apply the offset to. Give at most one of this and ``topic_name``.
            topic_name: Name of the topic to apply the offset to, such as ``"/imu/raw"``. Give at most one of this and
                ``topic``.
            timeline_source: Timeline source to apply the offset to. Give at most one of this and
                ``timeline_source_name``.
            timeline_source_name: Name of the timeline sources to apply the offset to, such as ``"header.stamp"``.
                Give at most one of this and ``timeline_source``.

        Returns:
            The timeline extents the offset changed, as Roboto returns them.

        Raises:
            TypeError: ``offset`` is not one of the :py:const:`~roboto.time.Time` types.
            ValueError: ``offset`` is a boolean, a negative number (an ``int``, ``float``, ``Decimal``, or numeric
                string), or a string that is neither seconds nor ISO 8601; or both of a mutually exclusive pair of
                selectors are given. Raised before any request is made.
            OverflowError: ``offset`` is an infinite ``float``, ``Decimal``, or string, such as ``"inf"``. Raised
                before any request is made.
            pydantic.ValidationError: ``offset`` converts to a negative number of nanoseconds, or to more than a signed
                64-bit integer holds. A subclass of ``ValueError``, raised before any request is made.

        Examples:
            Apply a file-wide offset:

            >>> file = File.from_id("fl_12345")
            >>> file.set_timeline_offset(1_700_000_000_000_000_000)

            Apply the same offset as a ``datetime``, the instant stored time 0 occurred:

            >>> import datetime
            >>> file.set_timeline_offset(datetime.datetime(2023, 11, 14, 22, 13, 20, tzinfo=datetime.timezone.utc))

            Apply an offset to a single topic by name:

            >>> file.set_timeline_offset(1_700_000_000_000_000_000, topic_name="/imu/raw")

            Apply an offset to a specific source on a topic:

            >>> file.set_timeline_offset(
            ...     500_000_000,
            ...     topic_name="data",
            ...     timeline_source_name="ts",
            ... )
        """
        if topic is not None and topic_name is not None:
            raise ValueError("Specify at most one of topic, topic_name.")
        if timeline_source is not None and timeline_source_name is not None:
            raise ValueError("Specify at most one of timeline_source, timeline_source_name.")

        entry = TimelineOffsetEntry(
            unix_epoch_offset_ns=to_epoch_nanoseconds(offset),
            topic_name=topic.topic_name if topic is not None else topic_name,
            timeline_source_id=(timeline_source.timeline_source_id if timeline_source is not None else None),
            timeline_source_name=timeline_source_name,
        )
        return self.set_timeline_offsets([entry])

    @experimental
    def set_timeline_offsets(
        self,
        offsets: list[TimelineOffsetEntry],
    ) -> list[TimelineExtentRecord]:
        """Apply several timeline offsets to this file in one request, all or none of them.

        Each entry carries a ``unix_epoch_offset_ns`` and optional selectors (``topic_name``,
        ``timeline_source_id``, ``timeline_source_name``) that limit which timelines it applies to. An entry with no
        selector applies to every timeline on the file. When two entries match the same timeline, the later one's
        offset applies.

        ``File.set_timeline_offset`` applies one offset.

        Args:
            offsets: Offsets to apply, at least one.

        Returns:
            The timeline extents the offsets changed, as Roboto returns them.

        Raises:
            pydantic.ValidationError: ``offsets`` is empty. Raised before any request is made.
            RobotoNotFoundException: The file carries no timeline data, or the selectors of every entry together
                match none of it.
            RobotoInvalidRequestException: An entry's offset would place the data it reaches, or a session time range
                declared over that data, before the Unix epoch or past the largest storable Unix-epoch nanosecond
                value. The whole request is refused and nothing is written.

        Examples:
            Apply per-topic offsets in a single request:

            >>> from roboto.domain.topics import TimelineOffsetEntry
            >>> file = File.from_id("fl_12345")
            >>> file.set_timeline_offsets(
            ...     [
            ...         TimelineOffsetEntry(unix_epoch_offset_ns=1_700_000_000_000_000_000, topic_name="/imu/raw"),
            ...         TimelineOffsetEntry(unix_epoch_offset_ns=1_700_000_000_000_000_000, topic_name="/camera/image"),
            ...     ]
            ... )
        """
        request = SetTimelineOffsetsRequest(offsets=offsets)
        return self.__roboto_client.post(
            f"v1/files/id/{self.file_id}/timeline-offsets",
            data=request,
        ).to_record_list(TimelineExtentRecord)

    def to_association(self) -> Association:
        """Return an association that refers to the version of this file this instance holds.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> association = file.to_association()
            >>> print(association.association_id)
            fl_12345
        """
        return Association.file(self.file_id, self.version)

    def to_dict(self) -> dict[str, typing.Any]:
        """Return this file's record as a dictionary of JSON-compatible values.

        Returns:
            :py:class:`~roboto.domain.files.FileRecord` of the file, as a JSON-compatible dictionary.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> file_dict = file.to_dict()
            >>> print(file_dict["relative_path"])
        """
        return self.__record.model_dump(mode="json")

    def update(
        self,
        description: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
        ingestion_complete: typing.Union[typing.Literal[True], NotSetType] = NotSet,
        device_id: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
    ) -> File:
        """Update this file's description, tags, metadata, ingestion status, or device.

        Each argument left unset (``NotSet``) leaves that property unchanged.

        Args:
            description: Human-readable description of the file. ``None`` clears it.
            metadata_changeset: Changes to the file's tags and metadata.
            ingestion_complete: ``True`` marks the file as fully ingested, as ``mark_ingested`` does.
            device_id: ID of the device the file's data came from. ``None`` clears it.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoDeviceNotFoundException: ``device_id`` names no device in the file's organization.

        Examples:
            >>> file = File.from_id("fl_12345")
            >>> file = file.update(description="Updated sensor data from highway test")
            >>> print(file.description)
            Updated sensor data from highway test

            Update the file's metadata and mark it ingested:

            >>> from roboto.updates import MetadataChangeset
            >>> changeset = MetadataChangeset(put_fields={"processed": True})
            >>> updated_file = file.update(metadata_changeset=changeset, ingestion_complete=True)
        """
        request = remove_not_set(
            UpdateFileRecordRequest(
                description=description,
                metadata_changeset=metadata_changeset,
                ingestion_complete=ingestion_complete,
                device_id=device_id,
            )
        )
        self.__record = self.__roboto_client.put(f"v1/files/record/{self.file_id}", data=request).to_record(FileRecord)
        return self

    def _resolve_link(self) -> File:
        """Return this file, or for a link, its target at the version the link pins.

        Raises:
            RobotoNotFoundException: This file is a link whose target, at the pinned version, no longer exists.
        """
        if not self.is_link:
            return self
        pointer = RobotoUri.parse(self.__record.uri)
        try:
            return File.from_id(pointer.id, version_id=pointer.version, roboto_client=self.__roboto_client)
        except RobotoNotFoundException:
            raise RobotoNotFoundException(
                f"'{self.relative_path}' is a link to {self.__record.uri}, which could not be found"
            ) from None
