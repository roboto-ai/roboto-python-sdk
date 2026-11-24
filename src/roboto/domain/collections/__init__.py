# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Collections: versioned containers that each group datasets, files, events, or sessions, one type per collection.

Use :py:class:`~roboto.domain.collections.Collection` to create and find collections and to add and remove their
members.
"""

from .collection import Collection
from .operations import (
    CreateCollectionRequest,
    UpdateCollectionRequest,
)
from .record import (
    CollectionChangeRecord,
    CollectionChangeSet,
    CollectionContentMode,
    CollectionRecord,
    CollectionResourceRef,
    CollectionResourceType,
)

__all__ = [
    "Collection",
    "CollectionChangeRecord",
    "CollectionChangeSet",
    "CollectionContentMode",
    "CollectionRecord",
    "CollectionResourceRef",
    "CollectionResourceType",
    "CreateCollectionRequest",
    "UpdateCollectionRequest",
]
