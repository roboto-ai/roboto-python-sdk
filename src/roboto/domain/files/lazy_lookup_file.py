# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Any, Callable

from .file import File


class LazyLookupFile(File):
    """A file handle that defers fetching the file until one of its attributes is first read or set.

    :py:meth:`~roboto.domain.files.FileSystem.upload_file` returns one, so a caller who never uses the uploaded file
    makes no request for it. The first attribute access calls ``hydrate_fn``, the function the handle was built with,
    and forwards that access, and every later one, to the :py:class:`~roboto.domain.files.File` it returns. If
    ``hydrate_fn`` raises, the exception propagates from that attribute access, and the next access calls
    ``hydrate_fn`` again.
    """

    def __init__(self, hydrate_fn: Callable[[], File]) -> None:
        # File.__init__ is not called. These attributes are set through object.__setattr__ because this class's
        # __setattr__ forwards to the fetched file.
        object.__setattr__(self, "_hydrate_fn", hydrate_fn)
        object.__setattr__(self, "_file", None)

    def _hydrate(self) -> None:
        if object.__getattribute__(self, "_file") is None:
            real = object.__getattribute__(self, "_hydrate_fn")()
            object.__setattr__(self, "_file", real)

    def __getattribute__(self, name: str) -> Any:
        # These names belong to the handle; every other name is read from, or set on, the fetched file.
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
