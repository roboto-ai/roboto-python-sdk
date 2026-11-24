# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections
import collections.abc
import typing

import pydantic
from pydantic import ConfigDict

from roboto.sentinels import NotSet, NotSetType
from roboto.updates import MetadataChangeset

from .record import DirectoryRecord, FileRecord


class CreateDirectoryRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.files.FileSystem.create_directory`."""

    name: str
    """Name of the directory to create."""

    error_if_exists: bool = False
    """Whether to fail with ``RobotoConflictException`` when the directory already exists.

    When ``False``, the response is the existing directory.
    """

    parent_path: typing.Optional[str] = None
    """Path of the parent directory, relative to the root of the association's files.

    ``None`` creates the directory at the root.
    """

    origination: typing.Optional[str] = None
    """What created the directory, such as ``roboto 0.30.0``. ``None`` records the caller's user ID."""

    create_intermediate_dirs: bool = False
    """Whether to create the directories along ``parent_path`` that do not exist.

    When ``False``, a missing parent directory fails the request with ``RobotoInvalidRequestException``.
    """


class CreateLinkRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.files.FileSystem.create_link`."""

    relative_path: str
    """Path of the link, relative to the root of the association's files. Missing parent directories are created."""

    target_file_id: str
    """ID of the file the link points at: a file, not a link or a directory, in the association's organization."""

    target_version: typing.Optional[int] = None
    """Version of the target file the link pins. ``None`` pins the target's current version."""


class DeleteDirectoriesRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.files.FileSystem.delete_directories`."""

    directory_paths: list[str]
    """Paths of the directories to delete, relative to the root of the association's files."""


class DeleteFileRequest(pydantic.BaseModel):
    """Request body naming a file to delete by its storage URI.

    No SDK method or Roboto route uses this model. To delete a file, call :py:meth:`~roboto.domain.files.File.delete`.
    """

    uri: str
    """Storage URI of the file to delete, such as ``s3://bucket/path/to/file.bag``."""


class FileRecordRequest(pydantic.BaseModel):
    """Request body holding a file's ID, tags, and metadata.

    No SDK method or Roboto route uses this model. To change a file's tags or metadata, call
    :py:meth:`~roboto.domain.files.File.update`.
    """

    file_id: str
    """ID of the file."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to set on the file."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata to set on the file."""


class ImportFileRequest(pydantic.BaseModel):
    """Request body for importing a file that is already in a bring-your-own bucket into a dataset.

    Sent by :py:meth:`~roboto.domain.files.File.import_one`, and by :py:meth:`~roboto.domain.files.File.import_batch`
    once per file. The file's contents stay in that bucket; Roboto stores only the file's record.
    """

    dataset_id: str
    """ID of the dataset to import the file into."""

    description: typing.Optional[str] = None
    """Human-readable description of the file."""

    device_id: typing.Optional[str] = None
    """ID of the device the file's data came from, or ``None`` if none is given."""

    tags: typing.Optional[list[str]] = None
    """Tags to set on the file. ``None`` sets none."""

    metadata: typing.Optional[dict[str, typing.Any]] = None
    """Key-value metadata to set on the file. ``None`` sets none."""

    relative_path: str
    """Path of the file within the dataset, such as ``logs/session1.bag``."""

    size: typing.Optional[int] = None
    """Size of the file in bytes.

    Required by :py:meth:`~roboto.domain.files.File.import_batch`, which fails with ``RobotoInvalidRequestException``
    when it is ``None``. :py:meth:`~roboto.domain.files.File.import_one` ignores it and reads the size from the bucket.
    """

    uri: str
    """Storage URI of the file, such as ``s3://bucket/path/to/file.bag``.

    The bucket must be registered as a bring-your-own bucket of the caller's organization.
    """


class QueryFilesRequest(pydantic.BaseModel):
    """Request body holding filter criteria for files.

    No SDK method or Roboto route uses this model. To search files, pass a
    :py:class:`~roboto.query.QuerySpecification` to :py:meth:`~roboto.domain.files.File.query`.
    """

    filters: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Filter criteria for files."""

    model_config = ConfigDict(extra="ignore")


class RenameFileRequest(pydantic.BaseModel):
    """Request body for renaming or moving a file among its association's files.

    Sent by :py:meth:`~roboto.domain.files.File.rename_file` and :py:meth:`~roboto.domain.files.FileSystem.rename_file`.
    The file keeps its ID; only its path changes.
    """

    association_id: str
    """ID of the dataset, device, device type, or organization whose files hold the file.

    Must be the file's own association. Naming another fails the request with ``RobotoInvalidRequestException``, so a
    rename cannot move a file between associations.
    """

    new_path: str
    """Path to move the file to, relative to the root of its association's files."""


class SignedUrlResponse(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.domain.files.File.get_signed_url`, which returns its ``url``."""

    url: str
    """Signed URL that downloads the file's contents without Roboto credentials, for one hour after it is issued."""

    etag: typing.Optional[str] = None
    """ETag of the stored object that the URL reads, as storage reported it when Roboto signed the URL.

    Compare it with the ``ETag`` header of each range that you download through the URL: a different value means
    that the file was replaced after the URL was signed. ``None`` when Roboto reports no ETag for the object.
    """


class UpdateFileRecordRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.files.File.update`.

    Each field left unset (``NotSet``) leaves that property of the file unchanged. Building it with
    ``ingestion_complete=False`` raises ``pydantic.ValidationError``.
    """

    description: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """Human-readable description of the file. ``None`` clears it."""

    device_id: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """ID of the device the file's data came from. ``None`` clears it."""

    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    """Changes to the file's tags and metadata."""

    ingestion_complete: typing.Union[typing.Literal[True], NotSetType] = NotSet
    """Whether to mark the file as fully ingested. Only ``True`` is accepted; no request marks a file not ingested."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)


class DirectoryContentsPage(pydantic.BaseModel):
    """Response body of ``GET /v1/datasets/{dataset_id}/files/directory-contents``.

    ``GET /v1/files/association/id/{association_id}/directory-contents`` returns it too. Each page holds files and
    directories directly inside one directory of an association's files.
    """

    files: collections.abc.Sequence[FileRecord]
    """Files on this page."""

    directories: collections.abc.Sequence[DirectoryRecord]
    """Directories on this page."""

    next_token: typing.Optional[str] = None
    """Token to pass as the ``after`` query parameter to fetch the next page, or ``None`` if this is the last page."""


class QueryDatasetFilesRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.files.FileSystem.list_files`.

    The same body lists the files of a dataset, a device, a device type, or an organization, despite its name.
    """

    page_token: typing.Optional[str] = None
    """Token from a previous page's response that resumes the listing after it. ``None`` starts at the first page."""

    include_patterns: typing.Optional[list[str]] = None
    """Gitignore-style patterns for the files to list, matched against each file's path.

    ``None`` or an empty list lists every file.
    """

    exclude_patterns: typing.Optional[list[str]] = None
    """Gitignore-style patterns for the files to leave out. ``None`` or an empty list leaves out none."""

    limit: typing.Optional[int] = None
    """Maximum number of files per page. ``None`` returns up to 1000."""

    sort_by: typing.Optional[str] = None
    """Field of the file record to sort by. ``None`` sorts by ``created``."""

    sort_direction: typing.Optional[str] = None
    """Sort direction, ``"ASC"`` or ``"DESC"``. ``None`` sorts in descending order."""

    include_inherited: bool = False
    """Whether listing a device's configurations also lists those of its device type.

    Setting it for any other association fails the request with ``RobotoInvalidRequestException``. Where the device
    and its type both have a file at the same path, only the device's is listed. Each listed file's
    ``association_id`` says whether it came from the device or from its type.
    """


class RenameDirectoryRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.files.FileSystem.rename_directory`.

    The directory's files and subdirectories move with it.
    """

    new_path: str
    """Path to move the directory to, relative to the root of the association's files."""

    old_path: str
    """Current path of the directory, relative to the root of the association's files."""
