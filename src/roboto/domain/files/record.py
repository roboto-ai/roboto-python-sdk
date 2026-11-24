# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import typing
from typing import TypeGuard
import urllib.parse

import pydantic

from ...compat import StrEnum
from ...exceptions import RobotoIllegalArgumentException
from ...uri import RobotoUri


class FileStatus(StrEnum):
    """Upload state of a file or directory.

    A file is ``Reserved`` while its upload is in progress and ``Available`` once the upload completes.
    """

    Available = "available"
    """Upload is complete: the file appears in listings and search, and can be downloaded and used by actions."""

    Deleted = "deleted"
    """The file or directory has been deleted and no longer appears in listings."""

    Reserved = "reserved"
    """Upload has begun but not completed, so the file does not appear in listings yet."""


class IngestionStatus(StrEnum):
    """How much of a file's data Roboto has ingested into topics.

    Ingestion extracts a file's data into topics, which makes it available for visualization and search. Roboto
    ingests many common robotics log formats, such as ROS bags, MCAP and ULog files, and custom ingestion actions can
    ingest others. A custom ingestion action marks each file it finishes with
    :py:meth:`~roboto.domain.files.File.mark_ingested`, which sets ``Ingested``.
    """

    NotIngested = "not_ingested"
    """No topic has been recorded for the file."""

    PartlyIngested = "partly_ingested"
    """At least one topic has been recorded for the file, but the file has not been marked ingested.

    Roboto sets this status when the first topic is recorded for a ``NotIngested`` file.
    """

    Ingested = "ingested"
    """The file has been marked fully ingested.

    Triggers that run when a file finishes ingestion act only on files with this status.
    """


class FileStorageType(StrEnum):
    """Where the object that holds a file's content is stored."""

    S3Imported = "imported"
    """The object is in a bucket the organization registered with Roboto, and was imported where it is.

    The object stays in the organization's bucket, and Roboto reads it with the access the organization granted. A
    link also has this storage type, although it stores no object.
    """

    S3Uploaded = "uploaded"
    """The object was uploaded through Roboto, to a Roboto-managed bucket or one the organization registered."""

    S3Directory = "directory"
    """The record is a directory, which has no object."""


class FSType(StrEnum):
    """Kind of entry in a file tree: a file, a directory, or a link."""

    File = "file"
    """File whose content is stored in an object of its own."""

    Directory = "directory"
    """Directory of files and other directories, which stores no object."""

    Link = "link"
    """Pointer to one version of another file in the same organization, which can belong to another dataset or device.

    A link sits among a device's, a device type's, or an organization's files, never a dataset's, and stores no
    object of its own. Its record's ``FileRecord.uri`` names the target and its version; downloading the link
    fetches the target at that version.
    """


class FileRecord(pydantic.BaseModel):
    """Data record of one version of a file, as the Roboto API returns it.

    A file is a data item uploaded or imported to a dataset, or added to a device's, a device type's, or an
    organization's files. :py:class:`~roboto.domain.files.File` wraps this record with methods that act on the file,
    and exposes it as :py:attr:`~roboto.domain.files.File.record`.
    """

    association_id: str
    """ID of the dataset, device, device type, or organization whose files include this file."""

    created: datetime.datetime
    """Time the file was created."""

    created_by: str = ""
    """Principal that created the file, as ``<type>:<id>``, such as ``user:<user_id>`` or ``invocation:iv_12345``."""

    description: typing.Optional[str] = None
    """Human-readable description of the file, or ``None`` if it has none."""

    device_id: typing.Optional[str] = None
    """ID of the device the file's data came from, or ``None`` if none was given."""

    file_id: str
    """Unique ID of the file, beginning with ``fl_``. Every version of the file has the same ID."""

    fs_type: FSType = FSType.File
    """Whether this record is a file with content of its own or a link to another file."""

    ingestable: bool = False
    """Whether the file is meant to be ingested.

    ``True`` when the file's path matched one of its organization's ingestion rules when this version was created or
    when the file was last renamed or moved, or when the file has since been partly or fully ingested. A file that is
    ingestable and whose ``ingestion_status`` is ``IngestionStatus.NotIngested`` is awaiting ingestion.
    """

    ingestion_status: IngestionStatus = IngestionStatus.NotIngested
    """How much of the file's data has been ingested into topics."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata on the file."""

    modified: datetime.datetime
    """Time the file was last modified."""

    modified_by: str
    """Principal that last modified the file, in the same ``<type>:<id>`` form as ``created_by``."""

    name: str
    """Name of the file, the final component of ``relative_path``. Unique within its directory."""

    org_id: str
    """ID of the organization that owns the file."""

    origination: str = ""
    """Free-form description of what added the file, such as the SDK version or the user that uploaded it."""

    parent_id: typing.Optional[str] = None
    """ID of the directory that contains the file, or ``None`` if the file is at the root."""

    relative_path: str
    """Path of the file from the root of its dataset's, device's, or organization's files, with forward slashes.

    Unique among those files. Downloading the file writes it to this path under the destination directory.
    """

    size: int
    """Size of the file's content in bytes. 0 for a link."""

    status: FileStatus = FileStatus.Available
    """Upload state of the file."""

    storage_type: FileStorageType = FileStorageType.S3Uploaded
    """Where the object that holds the file's content is stored."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the file."""

    upload_id: str = "NO_ID"
    """ID of the upload, import, or other operation that added the file. Files added together share it."""

    uri: str
    """Location of the object that holds the file's content, such as ``s3://<bucket>/<key>``.

    On a link, a ``roboto://file/<target_file_id>?v=<version>`` reference to the target instead.
    """

    version: int
    """Version of the file, starting at 1.

    Each change to the file, such as updating its metadata, renaming it, or uploading new content to its path, adds a
    version with the next number.
    """

    @property
    def is_link(self) -> bool:
        """Whether this record is a link to another file rather than a file with an object of its own."""
        return self.fs_type == FSType.Link

    @property
    def bucket(self) -> str:
        """Name of the bucket holding this file's object.

        Reading it on a link raises ``RobotoIllegalArgumentException``, since a link stores no object.
        """
        return urllib.parse.urlparse(self.__storage_uri(), allow_fragments=False).netloc

    @property
    def key(self) -> str:
        """Key of this file's object within ``bucket``.

        Reading it on a link raises ``RobotoIllegalArgumentException``, since a link stores no object.
        """
        return urllib.parse.urlparse(self.__storage_uri(), allow_fragments=False).path.lstrip("/")

    def __storage_uri(self) -> str:
        # A link's uri is a roboto:// pointer; read as S3 it names a bucket called "file".
        if self.is_link:
            target = RobotoUri.parse(self.uri)
            raise RobotoIllegalArgumentException(
                f"File {self.file_id} is a link to {self.uri} and stores no object of its own; "
                "File.download and File.get_signed_url on the link fetch its target, or load the target with "
                f"File.from_id({target.id!r}, version_id={target.version})."
            )
        return self.uri


class FileTag(enum.Enum):
    """Keys of the tags on the stored objects that hold files' content.

    Roboto uses this enum when it issues credentials for an upload, to limit the tags the upload may set, and when it
    copies files' objects, to tag the copies. These are tags on the objects in the bucket, separate from a file's
    ``FileRecord.tags``. Roboto assigns their values: the credentials it issues for an upload let the uploader set each
    tag only to the value Roboto assigned for that upload.
    """

    DatasetId = "dataset_id"
    """ID of the dataset whose files include the object's file.

    The objects of a dataset's files carry this tag, not ``AssociationId``, and
    an upload to a dataset must set it.
    """

    OrgId = "org_id"
    """ID of the organization that owns the object's file."""

    CommonPrefix = "common_prefix"
    """Key prefix under which Roboto stores the objects of the file's dataset, device, or organization."""

    TransactionId = "transaction_id"
    """ID of the upload that wrote the object, which is also the file's ``upload_id``."""

    AssociationId = "association_id"
    """ID of the organization, device, or device type whose files include the object's file.

    The objects of a dataset's files carry ``DatasetId`` instead.
    """


class DirectoryRecord(pydantic.BaseModel):
    """Data record of a directory, as the Roboto API returns it.

    A directory groups files and other directories by path within a dataset's, a device's, or an organization's
    files. Listing a directory's contents returns directory records alongside ``FileRecord`` objects;
    ``is_directory`` tells them apart.
    """

    association_id: str
    """ID of the dataset, device, device type, or organization whose files include this directory."""

    created: datetime.datetime
    """Time the directory was created."""

    created_by: str
    """Principal that created the directory, as ``<type>:<id>``, such as ``user:<user_id>``."""

    description: typing.Optional[str] = None
    """Human-readable description of the directory, or ``None`` if it has none."""

    directory_id: str
    """Unique ID of the directory."""

    fs_type: FSType = FSType.Directory
    """Kind of entry, always ``FSType.Directory``."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata on the directory."""

    modified: datetime.datetime
    """Time the directory was last modified."""

    modified_by: str
    """Principal that last modified the directory, in the same ``<type>:<id>`` form as ``created_by``."""

    name: str
    """Name of the directory, the final component of ``relative_path``. Unique within its parent directory."""

    org_id: str
    """ID of the organization that owns the directory."""

    origination: str
    """Free-form description of what created the directory."""

    parent_id: typing.Optional[str] = None
    """ID of the directory that contains this one, or ``None`` if this directory is at the root."""

    relative_path: str
    """Path of the directory from the root of its dataset's, device's, or organization's files."""

    status: FileStatus = FileStatus.Available
    """Whether the directory is available or deleted."""

    storage_type: FileStorageType = FileStorageType.S3Directory
    """Always ``FileStorageType.S3Directory``."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the directory."""

    upload_id: str
    """ID of the upload or other operation that created the directory."""


def is_directory(
    record: typing.Union[FileRecord, DirectoryRecord],
) -> TypeGuard[DirectoryRecord]:
    """Return whether ``record`` is a directory's record."""
    return record.fs_type == FSType.Directory


def is_file(record: typing.Union[FileRecord, DirectoryRecord]) -> TypeGuard[FileRecord]:
    """Return whether ``record`` is the record of a file with content of its own.

    A link's record is also a ``FileRecord``, but this returns ``False`` for it.
    """
    return record.fs_type == FSType.File
