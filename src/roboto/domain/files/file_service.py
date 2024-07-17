# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
from functools import partial
import pathlib
from typing import Any, Callable, Optional
import urllib.parse

import boto3.s3.transfer as s3_transfer

from ...http import RobotoClient
from ...logging import default_logger
from .file import File
from .progress import (
    NoopProgressMonitor,
    NoopProgressMonitorFactory,
    ProgressMonitor,
    ProgressMonitorFactory,
)
from .record import (
    CredentialProvider,
    FileRecord,
    FileTag,
)

# Used to change between showing progress bars for every file and "uploading X files"
MANY_FILES = 100


logger = default_logger()


class DynamicCallbackSubscriber(s3_transfer.BaseSubscriber):
    __on_done_cb: Optional[Callable[[Any], None]]
    __on_progress_cb: Optional[Callable[[Any], None]]
    __on_queued_cb: Optional[Callable[[Any], None]]

    def __init__(
        self,
        on_done_cb: Optional[Callable[[Any], None]] = None,
        on_progress_cb: Optional[Callable[[Any], None]] = None,
        on_queued_cb: Optional[Callable[[Any], None]] = None,
    ):
        self.__on_done_cb = on_done_cb
        self.__on_progress_cb = on_progress_cb
        self.__on_queued_cb = on_queued_cb

    def on_queued(self, future, **kwargs):
        if self.__on_queued_cb is not None:
            self.__on_queued_cb(future)

    def on_progress(self, future, bytes_transferred, **kwargs):
        if self.__on_progress_cb is not None:
            self.__on_progress_cb(future)

    def on_done(self, future, **kwargs):
        if self.__on_done_cb is not None:
            self.__on_done_cb(future)


class FileService:
    __roboto_client: RobotoClient

    @staticmethod
    def __transfer_manager_for_client_provider(
        credential_provider: CredentialProvider, max_concurrency: int = 8
    ):
        s3_client = File.generate_s3_client(credential_provider)
        transfer_config = s3_transfer.TransferConfig(
            use_threads=True, max_concurrency=max_concurrency
        )
        return s3_transfer.create_transfer_manager(s3_client, transfer_config)

    def __init__(self, roboto_client: RobotoClient):
        self.__roboto_client = roboto_client

    def download_files(
        self,
        file_generator: collections.abc.Generator[
            tuple[FileRecord, pathlib.Path], None, None
        ],
        credential_provider: CredentialProvider,
        progress_monitor_factory: ProgressMonitorFactory = NoopProgressMonitorFactory(),
        max_concurrency: int = 8,
    ) -> None:
        total_file_count = progress_monitor_factory.get_context().get(
            "total_file_count", 0
        )

        if total_file_count >= 20:
            self.__download_many_files(
                file_generator,
                credential_provider,
                progress_monitor_factory,
                max_concurrency,
            )
        else:
            for record, local_path in file_generator:
                File(record, self.__roboto_client).download(
                    local_path, credential_provider, progress_monitor_factory
                )

    def upload_files(
        self,
        bucket: str,
        file_generator: collections.abc.Generator[tuple[pathlib.Path, str], None, None],
        credential_provider: CredentialProvider,
        tags: Optional[dict[FileTag, str]] = None,
        progress_monitor_factory: ProgressMonitorFactory = NoopProgressMonitorFactory(),
        max_concurrency: int = 20,
    ) -> None:
        expected_file_count = progress_monitor_factory.get_context().get(
            "expected_file_count", "?"
        )

        if expected_file_count >= MANY_FILES:
            base_path = progress_monitor_factory.get_context().get("base_path", "?")
            expected_file_size = progress_monitor_factory.get_context().get(
                "expected_file_size", -1
            )

            progress_monitor = progress_monitor_factory.upload_monitor(
                source=f"{expected_file_count} files from {base_path}",
                size=expected_file_size,
            )
            self.upload_many_files(
                file_generator=file_generator,
                credential_provider=credential_provider,
                max_concurrency=max_concurrency,
                progress_monitor=progress_monitor,
                tags=tags,
            )
        else:
            for src, key in file_generator:
                self.upload_file(
                    local_path=src,
                    bucket=bucket,
                    key=key,
                    credential_provider=credential_provider,
                    tags=tags,
                    progress_monitor_factory=progress_monitor_factory,
                )

    def upload_many_files(
        self,
        file_generator: collections.abc.Iterable[tuple[pathlib.Path, str]],
        credential_provider: CredentialProvider,
        on_file_complete: Optional[Callable[[str, str], None]] = None,
        tags: Optional[dict[FileTag, str]] = None,
        progress_monitor: ProgressMonitor = NoopProgressMonitor(),
        max_concurrency: int = 20,
    ):
        extra_args: Optional[dict[str, Any]] = None
        if tags is not None:
            serializable_tags = {tag.value: value for tag, value in tags.items()}
            encoded_tags = urllib.parse.urlencode(serializable_tags)
            extra_args = {"Tagging": encoded_tags}

        with self.__transfer_manager_for_client_provider(
            credential_provider, max_concurrency
        ) as transfer_manager:
            for src, uri in file_generator:
                parsed_uri = urllib.parse.urlparse(uri)
                bucket = parsed_uri.netloc
                key = parsed_uri.path.lstrip("/")

                subscribers = [
                    s3_transfer.ProgressCallbackInvoker(progress_monitor.update)
                ]

                if on_file_complete is not None:
                    subscribers.append(
                        DynamicCallbackSubscriber(
                            on_done_cb=partial(on_file_complete, uri)
                        )
                    )

                transfer_manager.upload(
                    str(src),
                    bucket,
                    key,
                    extra_args=extra_args,
                    subscribers=subscribers,
                )

    def upload_file(
        self,
        local_path: pathlib.Path,
        bucket: str,
        key: str,
        credential_provider: CredentialProvider,
        tags: Optional[dict[FileTag, str]] = None,
        progress_monitor_factory: ProgressMonitorFactory = NoopProgressMonitorFactory(),
    ) -> None:
        upload_file_args: dict[str, Any] = {
            "Filename": str(local_path),
            "Key": key,
            "Bucket": bucket,
        }

        if tags is not None:
            serializable_tags = {tag.value: value for tag, value in tags.items()}
            encoded_tags = urllib.parse.urlencode(serializable_tags)
            upload_file_args["ExtraArgs"] = {"Tagging": encoded_tags}

        progress_monitor = progress_monitor_factory.upload_monitor(
            source=key, size=local_path.stat().st_size
        )
        upload_file_args["Callback"] = progress_monitor.update

        try:
            s3_client = File.generate_s3_client(credential_provider)
            s3_client.upload_file(**upload_file_args)
        finally:
            if progress_monitor is not None:
                progress_monitor.close()

    def __download_many_files(
        self,
        file_generator: collections.abc.Generator[
            tuple[FileRecord, pathlib.Path], None, None
        ],
        credential_provider: CredentialProvider,
        progress_monitor_factory: ProgressMonitorFactory = NoopProgressMonitorFactory(),
        max_concurrency: int = 8,
    ):
        transfer_manager = self.__transfer_manager_for_client_provider(
            credential_provider, max_concurrency
        )

        total_file_count = progress_monitor_factory.get_context().get(
            "total_file_count", 0
        )

        base_path = progress_monitor_factory.get_context().get("base_path", "?")

        progress_monitor = progress_monitor_factory.upload_monitor(
            source=f"{total_file_count} files from {base_path}",
            size=total_file_count,
            kwargs={"unit": "file"},
        )

        def on_done_cb(future):
            progress_monitor.update(1)

        subscriber = DynamicCallbackSubscriber(on_done_cb=on_done_cb)

        with transfer_manager:
            for record, local_path in file_generator:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                transfer_manager.download(
                    record.bucket,
                    record.key,
                    str(local_path),
                    subscribers=[subscriber],
                )
        progress_monitor.close()
