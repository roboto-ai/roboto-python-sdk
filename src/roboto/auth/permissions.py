# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum


class Permissions(enum.Enum):
    """Level of access that temporary credentials from Roboto grant: read only, or read and write.

    Roboto issues such credentials for a repository in its container image registry and for the files of a dataset.
    Request the least access the operation needs.
    """

    ReadOnly = "ReadOnly"
    """Read access, enough to pull a container image or download files."""

    ReadWrite = "ReadWrite"
    """Read and write access, enough to also push a container image or add and overwrite a dataset's files."""
