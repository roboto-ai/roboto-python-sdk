# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Any, Callable

from .file import File


class LazyLookupFile(File):
    """
    A File subclass that defers instantiation (hydration) of the real File until any non‐internal attribute is
    first accessed.

    This is useful for scenarios where we know how to dereference a File (e.g., by ID), and we want to return a handle
    in case the caller wants to work with it, but we don’t want to pay the cost of dereferencing it unless necessary.
    """

    def __init__(self, hydrate_fn: Callable[[], File]) -> None:
        # We don’t call super().__init__; we’ll get a real File from hydrate_fn.
        object.__setattr__(self, "_hydrate_fn", hydrate_fn)
        object.__setattr__(self, "_file", None)

    def _hydrate(self) -> None:
        if object.__getattribute__(self, "_file") is None:
            real = object.__getattribute__(self, "_hydrate_fn")()
            object.__setattr__(self, "_file", real)

    def __getattribute__(self, name: str) -> Any:
        if name in ["_hydrate", "_hydrate_fn", "_file"]:
            return object.__getattribute__(self, name)

        self._hydrate()
        real = object.__getattribute__(self, "_file")
        return getattr(real, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ["_hydrate", "_hydrate_fn", "_file"]:
            object.__setattr__(self, name, value)
        else:
            self._hydrate()
            real = object.__getattribute__(self, "_file")
            setattr(real, name, value)
