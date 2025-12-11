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
    _registry: typing.ClassVar[dict[str, typing.Type[ObjectStore]]] = {}

    @classmethod
    def register(cls, scheme: str):
        """
        Class Decorator.
        Registers the decorated class to handle the specific URI scheme.
        """

        def wrapper(store_cls: typing.Type[ObjectStore]):
            if scheme in cls._registry:
                raise ValueError(f"Scheme '{scheme}' is already registered to {cls._registry[scheme]}")
            cls._registry[scheme] = store_cls
            return store_cls

        return wrapper

    @classmethod
    def get_store_for_uri(cls, uri: str, credential_provider: CredentialProvider, **kwargs) -> ObjectStore:
        """
        Parses URI -> Finds Class -> Calls Class.create() -> Returns Instance
        """
        parsed = urllib.parse.urlparse(uri)
        scheme = parsed.scheme

        if scheme not in cls._registry:
            raise ValueError(f"No ObjectStore class registered for scheme: '{scheme}://'")

        store_class = cls._registry[scheme]

        # Delegate construction to the specific class
        return store_class.create(credential_provider=credential_provider, **kwargs)
