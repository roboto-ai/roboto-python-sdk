# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from ..compat import StrEnum


class ApiScope(StrEnum):
    """API scope of an access token: a group of requests the token can make.

    A token with some scopes can make only the requests they cover. A token created with no scopes, or with every
    scope, is not limited by scope. Set a token's scopes with :py:meth:`~roboto.domain.tokens.Token.create` or
    :py:meth:`~roboto.domain.devices.Device.create_token`. ``FilesImport`` and ``FilesUpload`` cover the same requests:
    either one lets a token both upload and import files.
    """

    ApiEverythingElse = "api.everything_else"
    """Every request no other scope covers, including requests that manage tokens.

    A developer's token usually holds it. A device token that only uploads data can leave it out, which limits what
    someone holding a leaked secret can do."""

    DatasetsCreate = "datasets.create"
    """Creating datasets."""

    FilesImport = "files.import"
    """Importing files from an external object store into a dataset."""

    FilesUpload = "files.upload"
    """Uploading files to a dataset."""

    @classmethod
    def all(cls) -> set[ApiScope]:
        """Return every scope."""
        return set(x for x in cls)

    @classmethod
    def minimal_uploader(cls) -> set[ApiScope]:
        """Return the scopes that let a token create datasets and add files to them, and nothing else."""
        return {cls.FilesImport, cls.FilesUpload, cls.DatasetsCreate}
