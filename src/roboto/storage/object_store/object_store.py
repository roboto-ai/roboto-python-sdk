# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import pathlib
import typing

T_co = typing.TypeVar("T_co", covariant=True)


class FutureLike(typing.Protocol[T_co]):
    """Protocol for future-like objects."""

    def result(self) -> T_co:
        """Wait for and return the result."""
        ...

    def done(self) -> bool:
        """Return True if the future is done."""
        ...


"""Callback which takes a number of bytes transferred to be periodically called."""
OnProgress: typing.TypeAlias = typing.Callable[[int], None]


@typing.runtime_checkable
class ObjectStore(typing.Protocol):
    @classmethod
    def create(cls, credential_provider: CredentialProvider, **kwargs) -> ObjectStore: ...

    def __enter__(self) -> ObjectStore: ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...

    def put(
        self, source: pathlib.Path, destination_uri: str, on_progress: typing.Optional[OnProgress] = None
    ) -> FutureLike[None]:
        """
        Uploads a local file to a specific cloud URI.

        Args:
            source: Local path to the file.
            destination_uri: Full URI (e.g., 's3://my-bucket/folder/data.csv')
            on_progress: Optional callback to be periodically called with the number of bytes uploaded.
        """
        ...

    def get(
        self, source_uri: str, destination: pathlib.Path, on_progress: typing.Optional[OnProgress] = None
    ) -> FutureLike[None]:
        """
        Downloads a file from a cloud URI to a local path.

        Parent directories of the destination path are created automatically if they don't exist.

        Args:
            source_uri: Full URI (e.g., 's3://my-bucket/folder/data.csv')
            destination: Local path where the file should be saved.
            on_progress: Optional callback to be periodically called with the number of bytes downloaded.
        """
        ...


class Credentials(typing.TypedDict):
    """
    This interface is driven by botocore.credentials.RefreshableCredentials
    """

    access_key: str
    secret_key: str
    token: str
    region: str
    expiry_time: typing.Optional[str]


CredentialProvider: typing.TypeAlias = typing.Callable[[], Credentials]
