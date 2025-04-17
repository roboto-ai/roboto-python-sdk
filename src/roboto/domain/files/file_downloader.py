# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import typing

from ...http.roboto_client import RobotoClient
from .file import File
from .file_creds import FileCredentialsHelper
from .file_service import FileService
from .progress import TqdmProgressMonitorFactory


def _pack_key(dataset_id: str, bucket: str) -> str:
    return f"{dataset_id}:{bucket}"


def _unpack_key(key: str) -> tuple[str, str]:
    parts = key.split(":")
    return parts[0], parts[1]


class FileDownloader:
    """A utility for downloading Roboto files."""

    def __init__(self, roboto_client: typing.Optional[RobotoClient]):
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__creds_helper = FileCredentialsHelper(self.__roboto_client)
        self.__file_service = FileService(self.__roboto_client)

    def download_files(
        self, out_path: pathlib.Path, files: collections.abc.Iterable[File]
    ) -> list[tuple[File, pathlib.Path]]:
        """
        Downloads the specified files to the provided local directory.

        The files could come from different datasets. All that is required
        is that the caller have appropriate file download permissions.

        An example use case is downloading files that are results of a search
        query:
            >>> import pathlib
            >>> from roboto import RobotoSearch
            >>> from roboto.domain.files import FileDownloader
            >>>
            >>> roboto_search = RobotoSearch()
            >>> file_downloader = FileDownloader()
            >>>
            >>> downloaded = file_downloader.download_files(
            ...     out_path=pathlib.Path("/dest/path"),
            ...     files=roboto_search.find_files('tags CONTAINS "CSV"')
            ... )
            >>>
            >>> for file, path in downloaded:
            ...     # Process the file

        Args:
            out_path: Destination directory for the downloaded files. It is created if it doesn't exist.
            files: Files to download.

        Returns:
            A list of (``File``, ``Path``) tuples, relating each provided file to its download path.
        """

        if not out_path.is_dir():
            out_path.mkdir(parents=True)

        grouped_files: dict[str, list[tuple[File, pathlib.Path]]] = (
            collections.defaultdict(list)
        )

        for file in files:
            key = _pack_key(file.dataset_id, file.record.bucket)
            grouped_files[key].append((file, out_path / file.relative_path))

        files_per_dataset: dict[str, int] = collections.defaultdict(int)
        for key, out_files in grouped_files.items():
            dataset_id, _ = _unpack_key(key)
            files_per_dataset[dataset_id] += len(out_files)

        for key, out_files in grouped_files.items():
            dataset_id, bucket = _unpack_key(key)

            self.__file_service.download_files(
                file_generator=((file[0].record, file[1]) for file in out_files),
                credential_provider=self.__creds_helper.get_dataset_download_creds_provider(
                    dataset_id, bucket
                ),
                progress_monitor_factory=TqdmProgressMonitorFactory(
                    concurrency=1,
                    ctx={
                        "base_path": dataset_id,
                        "total_file_count": files_per_dataset[dataset_id],
                    },
                ),
                max_concurrency=8,
            )

        return [file for files in grouped_files.values() for file in files]
