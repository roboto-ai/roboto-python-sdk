# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import os
import pathlib
import typing
import urllib.parse

import pathspec

from ...association import Association
from ...env import RobotoEnv
from ...exceptions import RobotoInternalException
from ...http import PaginatedList, RobotoClient
from ...logging import maybe_pluralize
from ...paths import excludespec_from_patterns, join_within
from ...progress import (
    NoopProgressMonitor,
    TqdmProgressMonitor,
)
from ...storage import DownloadableFile, FileService
from ...version import roboto_version
from .file import File
from .lazy_lookup_file import LazyLookupFile
from .operations import (
    CreateDirectoryRequest,
    CreateLinkRequest,
    QueryDatasetFilesRequest,
    RenameDirectoryRequest,
    RenameFileRequest,
)
from .record import DirectoryRecord, FileRecord

MAX_FILES_PER_MANIFEST = 500


class FileSystem:
    """The files and directories under one association: a dataset, a device, or the org itself.

    A ``FileSystem`` holds that association's directory tree and the operations on it: listing,
    uploading, downloading, renaming, and deleting files, and creating and renaming directories.
    Datasets, devices, and orgs each return one as :py:attr:`~roboto.domain.datasets.Dataset.files`,
    :py:attr:`~roboto.domain.devices.Device.files`, and :py:attr:`~roboto.domain.orgs.Org.files`.

    Every relative path a method takes or returns is relative to the root of the association's tree,
    which files of other associations do not share.
    """

    __association: Association
    __roboto_client: RobotoClient
    __file_service: FileService
    __org_id: typing.Optional[str]

    def __init__(
        self,
        association: Association,
        roboto_client: typing.Optional[RobotoClient] = None,
        file_service: typing.Optional[FileService] = None,
        org_id: typing.Optional[str] = None,
    ) -> None:
        """Bind to the files associated with ``association``.

        Args:
            association: The dataset, device, or org whose files this object works on.
            roboto_client: Roboto client instance. Uses the default if omitted.
            file_service: Transfers file contents to and from storage. Built from ``roboto_client`` if omitted.
            org_id: The org that owns the files. Sent as the caller's org on uploads and downloads, so a
                member of several orgs acts in the owning one.
        """
        self.__association = association
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__file_service = file_service or FileService(self.__roboto_client)
        self.__org_id = org_id

    def __repr__(self) -> str:
        return f"FileSystem({self.__association!r})"

    @property
    def association(self) -> Association:
        """The dataset, device, or org whose files this object works on."""
        return self.__association

    def create_directory(
        self,
        name: str,
        error_if_exists: bool = False,
        create_intermediate_dirs: bool = False,
        parent_path: typing.Optional[pathlib.Path] = None,
        origination: typing.Optional[str] = None,
    ) -> DirectoryRecord:
        """Create a directory among the association's files.

        Args:
            name: Name of the directory to create.
            error_if_exists: If True, raises an exception if the directory already exists.
            parent_path: Path of the parent directory. If None, creates the directory at the root of the
                association's files.
            origination: Optional string describing the source or context of the directory creation.
            create_intermediate_dirs: If True, creates intermediate directories in the path if they don't exist.
                If False, requires all parent directories to already exist.

        Raises:
            RobotoConflictException: If the directory already exists and error_if_exists is True.
            RobotoUnauthorizedException: If the caller lacks permission to create the directory.
            RobotoInvalidRequestException: If the directory name is invalid or the parent path does not exist
                (when create_intermediate_dirs is False).

        Returns:
            DirectoryRecord of the created directory.

        Examples:
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("lemi-01")
            >>> directory = device.files.create_directory("calib")
            >>> print(directory.relative_path)
            calib

            >>> directory = device.files.create_directory(
            ...     name="final",
            ...     parent_path=pathlib.Path("path/to/deep"),
            ...     create_intermediate_dirs=True,
            ... )
            >>> print(directory.relative_path)
            path/to/deep/final
        """
        if origination is None:
            origination = RobotoEnv.default().roboto_env or f"roboto {roboto_version()}"

        request = CreateDirectoryRequest(
            name=name,
            error_if_exists=error_if_exists,
            parent_path=str(parent_path) if parent_path is not None else None,
            origination=origination,
            create_intermediate_dirs=create_intermediate_dirs,
        )
        return self.__roboto_client.put(
            f"v1/files/association/id/{self.__association.association_id}/directory", data=request
        ).to_record(DirectoryRecord)

    def create_link(self, target: typing.Union[File, str], relative_path: str) -> File:
        """Put a link to another file at ``relative_path`` among the association's files.

        A link lets one file, such as a URDF in the org's own files, appear in many devices' files without
        being copied. It pins one version of its target: passing a :py:class:`File` pins that file's version,
        and passing a file ID pins the target's current version. Later versions of the target do not move
        the link; create the link again at the same path to re-point it, which adds a version to the link
        unless it already pins that target version. Missing parent directories are created. Downloading the
        link, or asking it for a signed URL, fetches the pinned version of the target.

        Args:
            target: The file to link to, or its ID. It must be a file in the same org, not a link or a directory.
            relative_path: Where the link sits, relative to the root of the association's files.

        Returns:
            The link, whose :py:attr:`~roboto.domain.files.File.is_link` is True.

        Raises:
            RobotoConflictException: A file or a directory already occupies ``relative_path``. The reverse is
                refused too: uploading a file to a link's path is a conflict until the link is deleted.
            RobotoInvalidRequestException: The target is a link or a directory, is in another org, or does not
                exist at the version to pin.
            RobotoUnauthorizedException: The caller cannot edit the association's files or view the target.

        Examples:
            >>> from roboto.domain import devices, orgs
            >>> urdf = orgs.Org.from_id("og_abc123").files.get_file_by_path("urdf/lemi/lemi.urdf")
            >>> device = devices.Device.from_id("lemi-01")
            >>> link = device.files.create_link(urdf, "urdf/lemi.urdf")
            >>> link.download(pathlib.Path("/tmp/lemi.urdf"))
        """
        request = (
            CreateLinkRequest(relative_path=relative_path, target_file_id=target.file_id, target_version=target.version)
            if isinstance(target, File)
            else CreateLinkRequest(relative_path=relative_path, target_file_id=target)
        )
        record = self.__roboto_client.put(
            f"v1/files/association/id/{self.__association.association_id}/link", data=request
        ).to_record(FileRecord)
        return File(record, self.__roboto_client, self.__file_service)

    def delete_files(
        self,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> None:
        """Delete the association's files that match the given patterns.

        Deletes files that match the specified include patterns while excluding
        those that match exclude patterns. Uses gitignore-style pattern matching
        for flexible file selection.

        Args:
            include_patterns: List of gitignore-style patterns for files to include.
                If None or empty, all files are considered for deletion. An empty list is
                treated as no filter (all files), not as "include nothing".
            exclude_patterns: List of gitignore-style patterns for files to exclude
                from deletion. Takes precedence over include patterns. If None or empty,
                no files are excluded.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to delete files.

        Notes:
            Pattern matching follows gitignore syntax. See https://git-scm.com/docs/gitignore
            for detailed pattern format documentation.

        Examples:
            >>> from roboto.domain import orgs
            >>> org = orgs.Org.from_id("og_abc123")
            >>> org.files.delete_files(include_patterns=["**/*.png"], exclude_patterns=["**/back_camera/**"])
        """
        for file in self.list_files(include_patterns, exclude_patterns):
            file.delete()

    def download_files(
        self,
        out_path: pathlib.Path,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
        print_progress: bool = True,
    ) -> list[tuple[FileRecord, pathlib.Path]]:
        """Download the association's files to a local directory.

        Downloads files that match the specified patterns to the given local directory.
        The files' directory structure is preserved in the download location.
        If the output directory doesn't exist, it will be created. Files are found with :py:meth:`list_files`,
        which does not return links yet, so no link is downloaded; download one with
        :py:meth:`~roboto.domain.files.File.download`.

        Args:
            out_path: Local directory path where files should be downloaded.
            include_patterns: List of gitignore-style patterns for files to include.
                If None or empty, all files are downloaded. An empty list is treated as
                no filter (all files), not as "include nothing".
            exclude_patterns: List of gitignore-style patterns for files to exclude
                from download. Takes precedence over include patterns. If None or empty,
                no files are excluded.
            print_progress: Whether to show a progress bar during download.

        Returns:
            List of tuples containing (FileRecord, local_path) for each downloaded file.

        Raises:
            RobotoIllegalArgumentException: A selected file's path resolves outside ``out_path``; nothing is
                downloaded.
            RobotoUnauthorizedException: Caller lacks permission to download files.

        Notes:
            Pattern matching follows gitignore syntax. See https://git-scm.com/docs/gitignore
            for detailed pattern format documentation.

        Examples:
            >>> import pathlib
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("lemi-01")
            >>> downloaded = device.files.download_files(pathlib.Path("/tmp/lemi-01"), include_patterns=["calib/**"])
            >>> print(f"Downloaded {len(downloaded)} files")
            Downloaded 2 files
        """
        if not out_path.is_dir():
            out_path.mkdir(parents=True)

        files = list(self.list_files(include_patterns, exclude_patterns))
        # Every destination is checked before any download starts, so a bad path downloads nothing.
        destinations = [join_within(out_path, file.relative_path) for file in files]
        # A link has no object; the bytes it downloads are its target's, which may sit under another association.
        sources = [file._resolve_link() for file in files]
        total_size = sum(source.record.size for source in sources)
        file_count = len(files)

        progress_monitor = (
            TqdmProgressMonitor(
                total=total_size,
                desc=f"Downloading {file_count} {maybe_pluralize('file', file_count)}",
            )
            if print_progress
            else NoopProgressMonitor()
        )

        downloads_by_association: dict[str, list[DownloadableFile]] = collections.defaultdict(list)
        for file, source, destination in zip(files, sources, destinations):
            downloads_by_association[source.association.association_id].append(
                {
                    "bucket_name": source.record.bucket,
                    "source_uri": source.record.uri,
                    "destination_path": destination,
                }
            )

        with progress_monitor:
            # Read credentials are minted per association, so each association's objects are fetched together.
            for association_id, downloadable_files in downloads_by_association.items():
                self.__file_service.download(
                    files=downloadable_files,
                    association=Association.from_id(association_id),
                    caller_org_id=self.__org_id,
                    on_progress=progress_monitor.update,
                )

        return [(file.record, destination) for file, destination in zip(files, destinations)]

    def get_file_by_path(
        self,
        relative_path: typing.Union[str, pathlib.Path],
        version_id: typing.Optional[int] = None,
    ) -> File:
        """Get a File instance for the association's file at the specified path.

        Args:
            relative_path: Path of the file relative to the root of the association's files.
            version_id: Specific version of the file to retrieve. If None, gets the latest version.

        Returns:
            File instance representing the file at the specified path.

        Raises:
            RobotoNotFoundException: The association has no file at the given path.
            RobotoUnauthorizedException: Caller lacks permission to access the file.

        Examples:
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("lemi-01")
            >>> file = device.files.get_file_by_path("manifest.json")
            >>> print(file.file_id)
            fl_xyz789

            >>> old_file = device.files.get_file_by_path("manifest.json", version_id=1)
            >>> print(old_file.version)
            1
        """
        url_quoted_file_path = urllib.parse.quote(str(relative_path), safe="")
        record = self.__roboto_client.get(
            f"v1/files/record/path/{url_quoted_file_path}/association/{self.__association.association_id}",
            query={"version_id": version_id} if version_id is not None else None,
        ).to_record(FileRecord)
        return File(record, self.__roboto_client)

    def list_directories(
        self,
    ) -> collections.abc.Generator[DirectoryRecord, None, None]:
        """Yield every directory among the association's files, at any depth.

        Examples:
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("lemi-01")
            >>> for directory in device.files.list_directories():
            ...     print(directory.relative_path)
            calib
            urdf
        """
        page_token: typing.Optional[str] = None
        while True:
            paginated_results = self.__roboto_client.get(
                f"v1/files/association/id/{self.__association.association_id}/directories",
                query={"page_token": page_token},
            ).to_record(PaginatedList[DirectoryRecord])
            for record in paginated_results.items:
                yield record
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    def list_files(
        self,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> collections.abc.Generator[File, None, None]:
        """List the association's files with optional pattern-based filtering.

        Returns all of the association's files that match the specified include patterns
        while excluding those that match exclude patterns. Uses gitignore-style
        pattern matching for flexible file selection.

        Args:
            include_patterns: List of gitignore-style patterns for files to include.
                If None or empty, all files are considered. An empty list is treated as
                no filter (all files), not as "include nothing".
            exclude_patterns: List of gitignore-style patterns for files to exclude.
                Takes precedence over include patterns. If None or empty, no files are excluded.

        Yields:
            File instances that match the specified patterns.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to list files.

        Notes:
            Pattern matching follows gitignore syntax. See https://git-scm.com/docs/gitignore
            for detailed pattern format documentation.

            Files appear in this list shortly after their upload completes, not instantly.

        Examples:
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("lemi-01")
            >>> for file in device.files.list_files():
            ...     print(file.relative_path)
            manifest.json
            calib/front_cam.yaml

            >>> for file in device.files.list_files(include_patterns=["calib/**"], exclude_patterns=["**/*.bak"]):
            ...     print(file.relative_path)
            calib/front_cam.yaml
        """
        page_token: typing.Optional[str] = None
        while True:
            paginated_results = self.__list_files_page(
                page_token=page_token,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
            )
            for record in paginated_results.items:
                yield File(record, self.__roboto_client)
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    def rename_directory(self, old_path: str, new_path: str) -> DirectoryRecord:
        """Rename or move a directory among the association's files.

        Both ``old_path`` and ``new_path`` are relative to the root of the association's files. Pass a
        ``new_path`` with fewer path components to move the directory up the tree, or
        a different leaf name at the same depth to rename in place.

        Args:
            old_path: Current relative path of the directory (e.g. ``"logs/session1"``).
            new_path: Target relative path of the directory (e.g. ``"session1"`` to move up one level).

        Returns:
            Updated :py:class:`~roboto.domain.files.DirectoryRecord` reflecting the new path.

        Raises:
            RobotoNotFoundException: No directory exists at ``old_path``.
            RobotoInvalidRequestException: ``new_path`` conflicts with an existing node or contains a cycle.

        Examples:
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("lemi-01")
            >>> device.files.rename_directory("calib/front", "front_calib")
        """
        response = self.__roboto_client.put(
            f"v1/files/association/id/{self.__association.association_id}/directory/rename",
            data=RenameDirectoryRequest(
                old_path=old_path,
                new_path=new_path,
            ),
        )

        return response.to_record(DirectoryRecord)

    def rename_file(self, file_id: str, new_path: str) -> FileRecord:
        """Rename or move a file among the association's files.

        ``new_path`` is relative to the root of the association's files. Pass a path with fewer components
        to move the file up the tree, a different name at the same depth to rename in
        place, or a path under a different directory to move sideways.

        The file's storage URI is unchanged; only its relative path changes.

        Args:
            file_id: ID of the file to rename or move.
            new_path: Target relative path for the file
                (e.g. ``"file.bag"`` to move to the root, or ``"other_dir/file.bag"``
                to move into an existing directory).

        Returns:
            Updated :py:class:`~roboto.domain.files.FileRecord` reflecting the new path.

        Raises:
            RobotoNotFoundException: No file with ``file_id`` exists.
            RobotoInvalidRequestException: ``new_path`` conflicts with an existing file,
                the parent directory does not exist, or the move would create a cycle.

        Examples:
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("lemi-01")
            >>> record = device.files.rename_file("fl_xyz789", "manifest.json")
            >>> record.relative_path
            'manifest.json'
        """
        response = self.__roboto_client.put(
            f"v1/files/{file_id}/rename",
            data=RenameFileRequest(
                association_id=self.__association.association_id,
                new_path=new_path,
            ),
        )

        return response.to_record(FileRecord)

    def upload_directory(
        self,
        directory_path: pathlib.Path,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
        delete_after_upload: bool = False,
        max_batch_size: int = MAX_FILES_PER_MANIFEST,
        print_progress: bool = True,
        device_id: typing.Optional[str] = None,
    ) -> None:
        """Upload all files and directories recursively from the specified directory path.

        Use ``include_patterns`` and ``exclude_patterns`` to control what files and directories are
        uploaded, and ``delete_after_upload`` to clean up your local filesystem after the uploads succeed.

        Args:
            directory_path: Local directory whose contents are uploaded, keeping its layout.
            include_patterns: gitignore-style patterns for files to include. If None, every file is included.
            exclude_patterns: gitignore-style patterns for files to exclude. Takes precedence over
                ``include_patterns``.
            delete_after_upload: If True, each uploaded local file is deleted once the uploads succeed.
            max_batch_size: Maximum number of files per upload transaction.
            print_progress: Whether to display an upload progress bar.
            device_id: Optional identifier of the device that generated this data.

        Notes:
            Both pattern lists follow the gitignore pattern format described
            in https://git-scm.com/docs/gitignore#_pattern_format.

        Examples:
            >>> import pathlib
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("lemi-01")
            >>> device.files.upload_directory(
            ...     pathlib.Path("/path/to/calibration"),
            ...     exclude_patterns=["**/*.log"],
            ... )
        """
        include_spec: typing.Optional[pathspec.PathSpec] = excludespec_from_patterns(include_patterns)
        exclude_spec: typing.Optional[pathspec.PathSpec] = excludespec_from_patterns(exclude_patterns)
        all_files = _list_directory_files(directory_path, include_spec=include_spec, exclude_spec=exclude_spec)
        file_destination_paths = {path: os.path.relpath(path, directory_path) for path in all_files}

        self.upload_files(all_files, file_destination_paths, max_batch_size, print_progress, device_id)

        if delete_after_upload:
            for file in all_files:
                if file.is_file():
                    file.unlink()

    def upload_file(
        self,
        file_path: pathlib.Path,
        file_destination_path: typing.Optional[str] = None,
        print_progress: bool = True,
        device_id: typing.Optional[str] = None,
    ) -> File:
        """Upload a single file associated with :py:attr:`association`.

        Args:
            file_path: Local file to upload.
            file_destination_path: Destination path among the association's files. Defaults to the
                file's own name at the root.
            print_progress: Whether to display an upload progress bar.
            device_id: Optional identifier of the device that generated this data.

        Returns:
            The uploaded file. Its record is fetched from the platform the first time it is read.

        Raises:
            RobotoInternalException: The upload reported success without reporting a file ID.

        Examples:
            >>> import pathlib
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("lemi-01")
            >>> device.files.upload_file(pathlib.Path("/path/to/manifest.json"))
        """
        if not file_destination_path:
            file_destination_path = file_path.name

        uploaded_file_ids = self.upload_files(
            [file_path],
            {file_path: file_destination_path},
            print_progress=print_progress,
            device_id=device_id,
        )

        file_id = uploaded_file_ids.get(file_path)
        if file_id is None:
            raise RobotoInternalException(
                f"Upload of '{file_path}' to '{self.__association.association_id}' completed without reporting a "
                "file ID."
            )

        return LazyLookupFile(
            lambda: File.from_id(
                file_id,
                roboto_client=self.__roboto_client,
            )
        )

    def upload_files(
        self,
        files: collections.abc.Iterable[pathlib.Path],
        file_destination_paths: collections.abc.Mapping[pathlib.Path, str] = {},
        max_batch_size: int = MAX_FILES_PER_MANIFEST,
        print_progress: bool = True,
        device_id: typing.Optional[str] = None,
    ) -> dict[pathlib.Path, str]:
        """Upload multiple files associated with :py:attr:`association`.

        Args:
            files: Local files to upload.
            file_destination_paths: Mapping from local path to destination path among the association's
                files. Files not in the mapping upload to the root under their own name.
            max_batch_size: Maximum number of files per upload transaction.
            print_progress: Whether to display an upload progress bar.
            device_id: Optional identifier of the device that generated this data.

        Returns:
            Mapping from each uploaded local path to the ID of the file record it created.

        Examples:
            >>> import pathlib
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("lemi-01")
            >>> file_ids = device.files.upload_files(
            ...     [pathlib.Path("/path/to/front_cam.yaml")],
            ...     file_destination_paths={pathlib.Path("/path/to/front_cam.yaml"): "calib/front_cam.yaml"},
            ... )
            >>> file_ids[pathlib.Path("/path/to/front_cam.yaml")]
            'fl_0123456789abcdef'
        """
        file_count = len(list(files))
        progress_monitor = (
            TqdmProgressMonitor(
                total=sum(file.stat().st_size for file in files),
                desc=f"Uploading {file_count} {maybe_pluralize('file', file_count)}",
            )
            if print_progress
            else NoopProgressMonitor()
        )
        with progress_monitor:
            return self.__file_service.upload(
                files=files,
                association=self.__association,
                destination_paths=file_destination_paths,
                batch_size=max_batch_size,
                device_id=device_id,
                on_progress=progress_monitor.update,
                caller_org_id=self.__org_id,
            )

    def __list_files_page(
        self,
        page_token: typing.Optional[str] = None,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> PaginatedList[FileRecord]:
        query_params: dict[str, typing.Any] = {}
        if page_token:
            query_params["page_token"] = str(page_token)

        request = QueryDatasetFilesRequest(
            page_token=page_token,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )
        return self.__roboto_client.post(
            f"v1/files/association/id/{self.__association.association_id}/query",
            data=request,
            query=query_params,
            idempotent=True,
        ).to_paginated_list(FileRecord)


def _list_directory_files(
    directory_path: pathlib.Path,
    include_spec: typing.Optional[pathspec.PathSpec] = None,
    exclude_spec: typing.Optional[pathspec.PathSpec] = None,
) -> collections.abc.Iterable[pathlib.Path]:
    all_files = set()

    for root, _, files in os.walk(directory_path):
        for file in files:
            should_include = include_spec is None or include_spec.match_file(file)
            should_exclude = exclude_spec is not None and exclude_spec.match_file(file)

            if should_include and not should_exclude:
                all_files.add(pathlib.Path(root, file))

    return all_files
