# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import pathlib
import typing

T_co = typing.TypeVar("T_co", covariant=True)
"""Type of the result a ``FutureLike`` holds."""


class FutureLike(typing.Protocol[T_co]):
    """Handle on an operation that runs in the background, such as a file transfer, and on its eventual result.

    ``ObjectStore.put`` and ``ObjectStore.get`` return one. A ``concurrent.futures.Future`` satisfies it.
    """

    def result(self) -> T_co:
        """Wait for the operation to finish and return its result.

        If the operation failed, this raises the exception it failed with.
        """
        ...

    def done(self) -> bool:
        """Return whether the operation has finished, successfully or not."""
        ...


OnProgress: typing.TypeAlias = typing.Callable[[int], None]
"""Function that receives the number of bytes transferred since its previous call, and returns nothing.

A transfer calls it as it runs. The number can be negative:
:py:class:`~roboto.storage.object_store.S3Store` passes a negative number when it retries a request, to take back the
progress that request had reported.
"""


@typing.runtime_checkable
class ObjectStore(typing.Protocol):
    """Client for one kind of cloud storage, which copies files between local disk and URIs in that storage.

    :py:meth:`~roboto.storage.FileService.upload` and :py:meth:`~roboto.storage.FileService.download` move file
    contents through it, with the store :py:class:`~roboto.storage.object_store.StoreRegistry` picks for a URI's
    scheme, so most code never calls it. Use a store as a context manager, and wait on every future it returns before
    the ``with`` block ends.
    """

    @classmethod
    def create(cls, credential_provider: CredentialProvider, **kwargs) -> ObjectStore:
        """Build a store that authenticates with the credentials ``credential_provider`` returns.

        Args:
            credential_provider: Function that returns temporary credentials. The store calls it once to start, and
                again whenever the credentials it holds are about to expire.
            **kwargs: Options particular to the store class.
        """
        ...

    def __enter__(self) -> ObjectStore:
        """Return this store."""
        ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Shut the store down and release its resources, such as its transfer threads."""
        ...

    def put(
        self, source: pathlib.Path, destination_uri: str, on_progress: typing.Optional[OnProgress] = None
    ) -> FutureLike[None]:
        """Start uploading a local file to a URI in the store.

        Args:
            source: Path of the local file to upload.
            destination_uri: Full URI to upload to, such as ``s3://<bucket>/<key>``.
            on_progress: Function called with the number of bytes uploaded since its previous call. ``None`` reports
                no progress.

        Returns:
            Future that resolves to ``None`` when the upload finishes, or raises the exception it failed with.
        """
        ...

    def get(
        self, source_uri: str, destination: pathlib.Path, on_progress: typing.Optional[OnProgress] = None
    ) -> FutureLike[None]:
        """Start downloading the object at a URI in the store to a local file.

        Creates any parent directories of ``destination`` that do not exist.

        Args:
            source_uri: Full URI to download from, such as ``s3://<bucket>/<key>``.
            destination: Local path to write the file to.
            on_progress: Function called with the number of bytes downloaded since its previous call. ``None``
                reports no progress.

        Returns:
            Future that resolves to ``None`` when the download finishes, or raises the exception it failed with.
        """
        ...


class _OptionalCredentials(typing.TypedDict, total=False):
    send_requests_to: typing.Optional[str]
    """URL that receives the requests signed with these credentials in place of S3.

    ``None``, or no such key, sends them to S3 directly.
    :py:attr:`~roboto.storage.RobotoCredentials.send_requests_to` describes where each request goes.
    """


class Credentials(_OptionalCredentials):
    """Temporary credentials an object store authenticates with, as a credential provider returns them.

    :py:meth:`~roboto.storage.RobotoCredentials.to_object_store_credentials` builds them from the credentials Roboto
    issues. :py:class:`~roboto.storage.object_store.S3Store` signs its requests with ``access_key``, ``secret_key``
    and ``token``, and calls the credential provider again as ``expiry_time`` nears.
    """

    access_key: str
    """AWS access key ID."""

    secret_key: str
    """AWS secret access key."""

    token: str
    """AWS session token to send with ``access_key`` and ``secret_key``."""

    region: str
    """AWS region of the bucket the credentials reach."""

    expiry_time: typing.Optional[str]
    """Time the credentials expire, as an ISO 8601 string.

    The type admits ``None``, but :py:class:`~roboto.storage.object_store.S3Store` fails on it.
    """


CredentialProvider: typing.TypeAlias = typing.Callable[[], Credentials]
"""Function that fetches temporary credentials, and returns them as ``Credentials``.

An object store calls it again to replace credentials that are about to expire.
"""
