# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Permission levels for temporary credentials, and who a dataset, collection or View is shared with.

Pass :py:class:`~roboto.auth.Permissions` to
:py:meth:`~roboto.image_registry.ImageRegistry.get_temporary_credentials` to choose what the credentials allow.
:py:meth:`~roboto.domain.collections.Collection.get_record_access` returns a collection's grants as a
:py:class:`~roboto.auth.RecordAccessResponse`, and :py:meth:`~roboto.domain.collections.Collection.edit_record_access`
adds and removes :py:class:`~roboto.auth.AccessGrant` values. :py:class:`~roboto.auth.EditAccessRequest` and
:py:class:`~roboto.auth.GetAccessResponse` are the deprecated tuple form they replace.
"""

from .fga import (
    AuthZTupleRecord,
    EditAccessRequest,
    GetAccessResponse,
)
from .permissions import Permissions
from .record_access import (
    AccessGrant,
    AccessRole,
    AccessSubject,
    AccessSubjectKind,
    EditRecordAccessRequest,
    RecordAccessResponse,
)

__all__ = (
    "AccessGrant",
    "AccessRole",
    "AccessSubject",
    "AccessSubjectKind",
    "AuthZTupleRecord",
    "EditAccessRequest",
    "EditRecordAccessRequest",
    "GetAccessResponse",
    "Permissions",
    "RecordAccessResponse",
)
