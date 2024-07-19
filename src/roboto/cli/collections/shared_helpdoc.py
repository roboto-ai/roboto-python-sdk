# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


COLLECTION_ID_HELP = "A unique ID used to reference a collection of Roboto resources."
COLLECTION_VERSION_HELP = (
    "An optional version for the provided collection ID."
    + " Allows caller to ensure that they're referencing an immutable representation of a given collection."
)
CONTENT_MODE_HELP = (
    "The type of content to return for a collection or set of collections. ``summary_only`` returns "
    + "only metadata, ``references`` will return each id in the collection, "
    + "and ``full`` will retrieve the full content of each resource in the collection."
)
