# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from ..compat import StrEnum


class ApiScope(StrEnum):
    """
    Scopes define the set of APIs a credential holder can access.
    """

    ApiEverythingElse = "api.everything_else"
    """Holder has access to all other APIs not covered by other scopes.

    A developer API token will likely want to include this scope, whereas an upload-only device token will likely
    want to omit it for principle of least privilege."""

    DatasetsCreate = "datasets.create"
    """Holder can create new datasets."""

    FilesImport = "files.import"
    """Holder can import existing files from an external object store into Roboto."""

    FilesUpload = "files.upload"
    """Holder can upload new files to Roboto's managed storage."""

    @classmethod
    def all(cls) -> set[ApiScope]:
        return set(x for x in cls)

    @classmethod
    def minimal_uploader(cls) -> set[ApiScope]:
        return {cls.FilesImport, cls.FilesUpload, cls.DatasetsCreate}
