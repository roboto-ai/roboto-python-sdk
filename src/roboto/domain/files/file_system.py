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
    DeleteDirectoriesRequest,
    QueryDatasetFilesRequest,
    RenameDirectoryRequest,
    RenameFileRequest,
)
from .record import DirectoryRecord, FileRecord

MAX_FILES_PER_MANIFEST = 500
"""Default ``max_batch_size`` of the upload methods: the most files uploaded in one batch."""


class FileSystem:
    """The files and directories of one dataset, device, device type, or organization, with the operations on them.

    That dataset, device, device type, or organization is the file system's ``association``. Get a ``FileSystem``
    from :py:attr:`~roboto.domain.datasets.Dataset.files` for a dataset's files,
    :py:attr:`~roboto.domain.devices.Device.configurations` for a device's configurations,
    ``device_type.configurations`` for a device type's configurations, or :py:attr:`~roboto.domain.orgs.Org.assets`
    for an organization's assets. Uploads and downloads act in the organization that owns the files, so a caller who
    belongs to several organizations need not name one.

    Every path a method takes or returns is relative to the root of the association's files. Each association has
    its own tree, so one path names different files in two associations.
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
        self.__association = association
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__file_service = file_service or FileService(self.__roboto_client)
        self.__org_id = org_id

    def __repr__(self) -> str:
        return f"FileSystem({self.__association!r})"

    @property
    def association(self) -> Association:
        """Dataset, device, device type, or organization whose files this object works on."""
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
            name: Name of the directory, unique within its parent directory.
            error_if_exists: Whether to raise ``RobotoConflictException`` when the directory already exists. When
                ``False``, the existing directory is returned.
            create_intermediate_dirs: Whether to create the directories along ``parent_path`` that do not exist.
                When ``False``, every directory along it must already exist.
            parent_path: Path of the directory to create this one in. ``None`` creates it at the root.
            origination: What created the directory, recorded on it. ``None`` records the value of the
                ``ROBOTO_ENV`` environment variable when it is set, and ``roboto <SDK version>`` otherwise.

        Returns:
            Record of the created directory, or of the existing one.

        Raises:
            RobotoConflictException: The directory already exists and ``error_if_exists`` is ``True``.
            RobotoInvalidRequestException: The name is invalid, or a directory along ``parent_path`` does not exist
                and ``create_intermediate_dirs`` is ``False``.

        Examples:
            Create a directory at the root of a device's configurations:

            >>> import pathlib
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("rover-01")
            >>> directory = device.configurations.create_directory("calib")
            >>> print(directory.relative_path)
            calib

            Create a nested directory, with the directories along its parent path:

            >>> directory = device.configurations.create_directory(
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
            self.__route(dataset_route="directory", association_route="directory"), data=request
        ).to_record(DirectoryRecord)

    def create_link(self, target: typing.Union[File, str], relative_path: str) -> File:
        """Put a link to another file at ``relative_path`` among the association's files.

        Links can be created in a device's or a device type's configurations and in an organization's assets, but not
        in a dataset's files. A link lets one file appear in many devices' configurations without being copied.

        A link pins one version of its target: passing a :py:class:`~roboto.domain.files.File` pins that file's
        version, and passing a file ID pins the target's current version. Later versions of the target do not move the
        link; create the link again at the same path to point it at the new version, which adds a version to the link
        unless it already pins that target version. Missing parent directories are created. Downloading the link, or
        asking it for a signed URL, fetches the pinned version of the target. While the link exists, uploading a file
        to its path raises ``RobotoConflictException``.

        Args:
            target: File to link to, or its ID. It must be a file in the same organization, not a link or a directory.
            relative_path: Path of the link.

        Returns:
            The link, whose :py:attr:`~roboto.domain.files.File.is_link` is ``True``.

        Raises:
            RobotoConflictException: A file or a directory already occupies ``relative_path``.
            RobotoInvalidRequestException: The association is a dataset, or the target is a link or a directory, is in
                another organization, or does not exist at the version to pin.

        Examples:
            >>> import pathlib
            >>> from roboto.domain import devices, orgs
            >>> runbook = orgs.Org.from_id("og_12345").assets.get_file_by_path("runbooks/field_service.pdf")
            >>> device = devices.Device.from_id("rover-01")
            >>> link = device.configurations.create_link(runbook, "runbooks/field_service.pdf")
            >>> link.download(pathlib.Path("/tmp/field_service.pdf"))
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

    def delete_directories(self, directory_paths: list[str]) -> None:
        """Delete directories from the association's files, with every file and directory beneath them.

        The directories stop appearing in listings when this returns. The files and directories beneath them are
        removed in the background, so they can still appear for a short while. Deleting a directory that no longer
        exists succeeds and changes nothing, and a path that names a file deletes that file. A link beneath a deleted
        directory is deleted, but the file it points at is kept unless it is beneath a deleted directory too. Links
        elsewhere that point at deleted files stop working. On a device's configurations, only the device's own
        directories are deleted, never its device type's.

        Args:
            directory_paths: Paths of the directories to delete.

        Examples:
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("rover-01")
            >>> device.configurations.delete_directories(["calib/old", "scratch"])
        """
        self.__roboto_client.post(
            self.__route(dataset_route="files/delete-directories", association_route="delete-directories"),
            data=DeleteDirectoriesRequest(directory_paths=directory_paths),
        )

    def delete_files(
        self,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> None:
        """Delete the association's files that match the given patterns.

        Deletes the matching files one request per file, through :py:meth:`~roboto.domain.files.File.delete`, whose
        failures also apply. When one request fails, the files deleted before it stay deleted. A matching link is
        deleted; the file it points at is not. On a device's configurations, only the device's own files are deleted;
        delete its device type's through ``device_type.configurations``.

        Args:
            include_patterns: Gitignore-style patterns for the files to delete. ``None`` or an empty list selects
                every file.
            exclude_patterns: Gitignore-style patterns for files to keep. Takes precedence over
                ``include_patterns``. ``None`` or an empty list keeps none.

        Note:
            Patterns follow the gitignore format described at https://git-scm.com/docs/gitignore.

        Examples:
            Delete every PNG file in an organization's assets except those under a ``back_camera`` directory:

            >>> from roboto.domain import orgs
            >>> org = orgs.Org.from_id("og_12345")
            >>> org.assets.delete_files(include_patterns=["**/*.png"], exclude_patterns=["**/back_camera/**"])
        """
        for file in self.list_files(include_patterns, exclude_patterns):
            file.delete()

    def download_files(
        self,
        out_path: pathlib.Path,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
        print_progress: bool = True,
        *,
        include_inherited: bool = False,
    ) -> list[tuple[FileRecord, pathlib.Path]]:
        """Download the association's files that match the given patterns to a local directory.

        Each file is saved at its path under ``out_path``. A link is saved at its own path, with the contents of the
        file version it pins.

        Args:
            out_path: Local directory to download into. Created, with any missing parents, if it does not exist.
            include_patterns: Gitignore-style patterns for the files to download. ``None`` or an empty list selects
                every file.
            exclude_patterns: Gitignore-style patterns for files to skip. Takes precedence over
                ``include_patterns``. ``None`` or an empty list skips none.
            print_progress: Whether to show a progress bar during the download.
            include_inherited: Whether, for a device's configurations, to also download its device type's, selected
                as ``list_files`` selects them.

        Returns:
            One ``(record, local_path)`` pair per downloaded file.

        Raises:
            RobotoIllegalArgumentException: A selected file's path resolves outside ``out_path``. Nothing is
                downloaded.
            RobotoInvalidRequestException: ``include_inherited`` is ``True`` for anything but a device's
                configurations.
            RobotoNotFoundException: A selected link pins a file version that no longer exists. Nothing is
                downloaded.

        Note:
            Patterns follow the gitignore format described at https://git-scm.com/docs/gitignore.

        Examples:
            Download a device's calibration files:

            >>> import pathlib
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("rover-01")
            >>> downloaded = device.configurations.download_files(
            ...     pathlib.Path("/tmp/rover-01"), include_patterns=["calib/**"]
            ... )
            >>> print(f"Downloaded {len(downloaded)} files")
        """
        if not out_path.is_dir():
            out_path.mkdir(parents=True)

        files = list(self.list_files(include_patterns, exclude_patterns, include_inherited=include_inherited))
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
        """Fetch the association's file at a path.

        On a device's configurations, only the device's own files are looked up. A file the device inherits from its
        device type is not found here; look it up through ``device_type.configurations``.

        Args:
            relative_path: Path of the file.
            version_id: Version of the file to fetch. ``None`` fetches the latest version.

        Raises:
            RobotoNotFoundException: The association has no file at this path.

        Examples:
            Fetch a device's manifest:

            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("rover-01")
            >>> file = device.configurations.get_file_by_path("manifest.json")

            Fetch the manifest's first version:

            >>> old_file = device.configurations.get_file_by_path("manifest.json", version_id=1)
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
            >>> device = devices.Device.from_id("rover-01")
            >>> for directory in device.configurations.list_directories():
            ...     print(directory.relative_path)
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
        *,
        include_inherited: bool = False,
    ) -> collections.abc.Generator[File, None, None]:
        """List the association's files that match the given patterns.

        Links are listed alongside files; :py:attr:`~roboto.domain.files.File.is_link` tells them apart.

        Args:
            include_patterns: Gitignore-style patterns for the files to list. ``None`` or an empty list selects
                every file.
            exclude_patterns: Gitignore-style patterns for files to leave out. Takes precedence over
                ``include_patterns``. ``None`` or an empty list leaves out none.
            include_inherited: Whether, for a device's configurations, to also list its device type's. Where the
                device and its type both have a file at the same path, only the device's is listed.
                ``file.association.is_device_type`` tells which files came from the type.

        Yields:
            Each matching :py:class:`~roboto.domain.files.File`, fetched a page at a time as the generator
            advances.

        Raises:
            RobotoInvalidRequestException: ``include_inherited`` is ``True`` for anything but a device's
                configurations. It surfaces on the first iteration.

        Note:
            Patterns follow the gitignore format described at https://git-scm.com/docs/gitignore. A file appears
            here shortly after its upload completes, not at once.

            Only this method and ``download_files`` include a device type's
            configurations. ``get_file_by_path``, ``rename_file``, ``delete_files`` and ``delete_directories`` act
            on the device's own configurations only, and :py:meth:`~roboto.domain.files.File.delete` on a file
            from the type deletes it from the type, for every device of that type.

        Examples:
            List every file in a device's configurations:

            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("rover-01")
            >>> for file in device.configurations.list_files():
            ...     print(file.relative_path)

            List the calibration files, except backups:

            >>> for file in device.configurations.list_files(
            ...     include_patterns=["calib/**"], exclude_patterns=["**/*.bak"]
            ... ):
            ...     print(file.relative_path)
        """
        page_token: typing.Optional[str] = None
        while True:
            paginated_results = self.__list_files_page(
                page_token=page_token,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
                include_inherited=include_inherited,
            )
            for record in paginated_results.items:
                yield File(record, self.__roboto_client)
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    def rename_directory(self, old_path: str, new_path: str) -> DirectoryRecord:
        """Rename or move a directory among the association's files, with everything beneath it.

        The last component of ``new_path`` becomes the directory's name, and the directory at the rest of
        ``new_path`` becomes its parent.

        Args:
            old_path: Current path of the directory, such as ``"logs/session1"``.
            new_path: Path to move the directory to, such as ``"session1"`` to move it up one level.

        Returns:
            Record of the moved directory.

        Raises:
            RobotoInvalidRequestException: ``new_path`` is empty or the same as ``old_path``, no directory exists at
                its parent path, that parent is the directory itself or beneath it, or the name is taken there.
            RobotoNotFoundException: No directory exists at ``old_path``.

        Examples:
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("rover-01")
            >>> device.configurations.rename_directory("calib/front", "front_calib")
        """
        response = self.__roboto_client.put(
            self.__route(dataset_route="directory/rename", association_route="directory/rename"),
            data=RenameDirectoryRequest(
                old_path=old_path,
                new_path=new_path,
            ),
        )

        return response.to_record(DirectoryRecord)

    def rename_file(self, file_id: str, new_path: str) -> FileRecord:
        """Rename or move one of the association's files.

        The file keeps its ID, topics, and events. The rename adds a version of the file at ``new_path``.

        Args:
            file_id: ID of the file to rename or move.
            new_path: Path to move the file to, such as ``"file.bag"`` to move it to the root or
                ``"other_dir/file.bag"`` to move it into an existing directory.

        Returns:
            Record of the file's new version.

        Raises:
            RobotoInvalidRequestException: No directory exists at ``new_path``'s parent path, the name is taken
                there, or the file belongs to another association.
            RobotoNotFoundException: No file has this ID.

        Examples:
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("rover-01")
            >>> record = device.configurations.rename_file("fl_12345", "manifest.json")
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
        """Upload every file under a local directory, at any depth, to the association's files.

        Each file is uploaded to its path relative to ``directory_path``, so the association's files mirror the local
        layout.

        Args:
            directory_path: Local directory whose files to upload.
            include_patterns: Gitignore-style patterns for the files to upload. ``None`` uploads every file; an
                empty list uploads none.
            exclude_patterns: Gitignore-style patterns for files to skip. Takes precedence over
                ``include_patterns``.
            delete_after_upload: Whether to delete each uploaded local file once every upload has succeeded.
                Directories are kept.
            max_batch_size: Maximum number of files per upload batch. Each batch finishes uploading before the
                next starts.
            print_progress: Whether to show a progress bar during the upload.
            device_id: ID of the device that produced the files' data.

        Note:
            Patterns follow the gitignore format described at https://git-scm.com/docs/gitignore#_pattern_format,
            but each is matched against a file's name only, not its path under ``directory_path``. A pattern
            naming a directory, such as ``"__pycache__/"``, matches no file.

        Examples:
            Upload a calibration directory to a device's configurations, skipping log files:

            >>> import pathlib
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("rover-01")
            >>> device.configurations.upload_directory(
            ...     pathlib.Path("/path/to/calibration"),
            ...     exclude_patterns=["*.log"],
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
        """Upload one local file to the association's files.

        Args:
            file_path: Local file to upload.
            file_destination_path: Path to upload the file to. ``None`` uploads it to the root under its own name.
            print_progress: Whether to show a progress bar during the upload.
            device_id: ID of the device that produced the file's data.

        Returns:
            The uploaded file. Its record is fetched from Roboto the first time it is read.

        Raises:
            RobotoInternalException: The upload finished without reporting the new file's ID.

        Examples:
            >>> import pathlib
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("rover-01")
            >>> device.configurations.upload_file(pathlib.Path("/path/to/manifest.json"))
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
        """Upload several local files to the association's files.

        Args:
            files: Local files to upload, as a list or another collection that can be iterated more than once.
            file_destination_paths: Path to upload each local file to, keyed by local path. A file not in the
                mapping is uploaded to the root under its own name.
            max_batch_size: Maximum number of files per upload batch. Each batch finishes uploading before the
                next starts.
            print_progress: Whether to show a progress bar during the upload.
            device_id: ID of the device that produced the files' data.

        Returns:
            ID of the file each local path was uploaded as, keyed by local path.

        Raises:
            ValueError: Two local files would be uploaded to the same path. Raised before any upload starts.

        Examples:
            >>> import pathlib
            >>> from roboto.domain import devices
            >>> device = devices.Device.from_id("rover-01")
            >>> file_ids = device.configurations.upload_files(
            ...     [pathlib.Path("/path/to/front_cam.yaml")],
            ...     file_destination_paths={pathlib.Path("/path/to/front_cam.yaml"): "calib/front_cam.yaml"},
            ... )
            >>> print(file_ids[pathlib.Path("/path/to/front_cam.yaml")])
        """
        files = list(files)
        file_count = len(files)
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

    def __route(self, *, dataset_route: str, association_route: str) -> str:
        """Build the API route for one operation on the association's files.

        A dataset's files go through the dataset routes (``v1/datasets/{dataset_id}/...``), which every Roboto
        deployment serves. A device's, a device type's or the organization's files go through the association routes
        (``v1/files/association/id/{association_id}/...``).

        Args:
            dataset_route: The rest of the route after ``v1/datasets/{dataset_id}/``.
            association_route: The rest of the route after ``v1/files/association/id/{association_id}/``.
        """
        association_id = self.__association.association_id
        if self.__association.is_dataset:
            return f"v1/datasets/{association_id}/{dataset_route}"
        return f"v1/files/association/id/{association_id}/{association_route}"

    def __list_files_page(
        self,
        page_token: typing.Optional[str] = None,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
        include_inherited: bool = False,
    ) -> PaginatedList[FileRecord]:
        query_params: dict[str, typing.Any] = {}
        if page_token:
            query_params["page_token"] = str(page_token)

        request = QueryDatasetFilesRequest(
            page_token=page_token,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            include_inherited=include_inherited,
        )
        return self.__roboto_client.post(
            self.__route(dataset_route="files/query", association_route="query"),
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
