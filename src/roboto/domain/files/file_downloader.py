# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import typing

from ...http.roboto_client import RobotoClient
from ...logging import default_logger
from .file import File
from .file_creds import FileCredentialsHelper
from .file_service import FileService
from .progress import TqdmProgressMonitorFactory

logger = default_logger()


class FileDownloadCandidate(typing.NamedTuple):
    """A file being considered for download, with its target path and download status."""

    file: File
    path: pathlib.Path
    requires_download: bool


def _pack_key(dataset_id: str, bucket: str) -> str:
    return f"{dataset_id}:{bucket}"


def _unpack_key(key: str) -> tuple[str, str]:
    parts = key.split(":")
    return parts[0], parts[1]


class FileDownloader:
    """A utility for downloading Roboto files."""

    def __init__(self, roboto_client: typing.Optional[RobotoClient] = None):
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
            ...     out_path=pathlib.Path("/dest/path"), files=roboto_search.find_files('tags CONTAINS "CSV"')
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
        grouped_files: dict[str, list[FileDownloadCandidate]] = collections.defaultdict(list)

        for file in files:
            key = _pack_key(file.dataset_id, file.record.bucket)
            local_path = out_path / file.file_id / str(file.version) / pathlib.Path(file.relative_path).name
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # skip download if file already exists locally
            # file equivalence heuristics:
            #   - file_id + version match
            #   - size matches
            requires_download = True
            if local_path.exists():
                stat = local_path.stat()
                local_file_size_matches_remote = stat.st_size == file.record.size
                if local_file_size_matches_remote:
                    logger.debug(
                        "%s (%s@v%d) already downloaded to roboto cache.",
                        file.relative_path,
                        file.file_id,
                        file.version,
                    )
                    requires_download = False

            grouped_files[key].append(
                FileDownloadCandidate(file=file, path=local_path, requires_download=requires_download)
            )

        download_count_per_dataset: dict[str, int] = collections.defaultdict(int)
        for key, out_files in grouped_files.items():
            dataset_id, _ = _unpack_key(key)
            download_count_per_dataset[dataset_id] += sum(1 for candidate in out_files if candidate.requires_download)

        for key, out_files in grouped_files.items():
            dataset_id, bucket = _unpack_key(key)

            self.__file_service.download_files(
                file_generator=(
                    (candidate.file.record, candidate.path) for candidate in out_files if candidate.requires_download
                ),
                credential_provider=self.__creds_helper.get_dataset_download_creds_provider(dataset_id, bucket),
                progress_monitor_factory=TqdmProgressMonitorFactory(
                    concurrency=1,
                    ctx={
                        "base_path": dataset_id,
                        "total_file_count": download_count_per_dataset[dataset_id],
                    },
                ),
                max_concurrency=8,
            )

        return [(candidate.file, candidate.path) for files in grouped_files.values() for candidate in files]
