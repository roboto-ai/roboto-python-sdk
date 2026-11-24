# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import typing
import urllib.parse

from .object_store import (
    CredentialProvider,
    ObjectStore,
)


class StoreRegistry:
    """Registry of object store classes, keyed by the URI scheme each one handles.

    :py:meth:`~roboto.storage.FileService.upload` and :py:meth:`~roboto.storage.FileService.download` choose the store
    for each file through it, so most code never calls it. :py:class:`~roboto.storage.object_store.S3Store` registers
    itself for ``s3``. Registrations are held on the class, so they apply to the whole process.
    """

    _registry: typing.ClassVar[dict[str, typing.Type[ObjectStore]]] = {}

    @classmethod
    def register(cls, scheme: str):
        """Build a class decorator that registers the decorated store class for a URI scheme.

        The decorator returns the class unchanged.

        Args:
            scheme: URI scheme the class handles, without ``://``, such as ``s3``.

        Raises:
            ValueError: Another class is already registered for ``scheme``. Raised when the decorator is applied.
        """

        def wrapper(store_cls: typing.Type[ObjectStore]):
            if scheme in cls._registry:
                raise ValueError(f"Scheme '{scheme}' is already registered to {cls._registry[scheme]}")
            cls._registry[scheme] = store_cls
            return store_cls

        return wrapper

    @classmethod
    def get_store_for_uri(cls, uri: str, credential_provider: CredentialProvider, **kwargs) -> ObjectStore:
        """Build a store of the class registered for a URI's scheme.

        Only the scheme is read from ``uri``; the store is built by the registered class's
        :py:meth:`~roboto.storage.object_store.ObjectStore.create`.

        Args:
            uri: URI of an object in the store, such as ``s3://my-bucket/folder/data.csv``.
            credential_provider: Callable that returns credentials for the store, passed to ``create``.
            **kwargs: Further arguments passed to ``create``.

        Raises:
            ValueError: No class is registered for the URI's scheme.
        """
        parsed = urllib.parse.urlparse(uri)
        scheme = parsed.scheme
        if scheme not in cls._registry:
            raise ValueError(f"No ObjectStore class registered for scheme: '{scheme}://'")

        store_class = cls._registry[scheme]
        return store_class.create(credential_provider=credential_provider, **kwargs)
