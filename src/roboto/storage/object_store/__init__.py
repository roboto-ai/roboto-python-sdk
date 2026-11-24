# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Copying of files between local disk and the cloud storage Roboto keeps them in, using credentials Roboto issues.

:py:meth:`~roboto.storage.FileService.upload` and :py:meth:`~roboto.storage.FileService.download` pick a store from
:py:class:`~roboto.storage.object_store.StoreRegistry` by the scheme of a file's URI (``s3://`` selects
:py:class:`~roboto.storage.object_store.S3Store`), so most code never calls this package directly.
"""

from .object_store import (
    CredentialProvider,
    Credentials,
    FutureLike,
    ObjectStore,
    OnProgress,
)
from .registry import StoreRegistry
from .s3 import S3Store

__all__ = (
    "Credentials",
    "CredentialProvider",
    "FutureLike",
    "ObjectStore",
    "OnProgress",
    "StoreRegistry",
    "S3Store",
)
