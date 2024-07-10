# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum


class Permissions(enum.Enum):
    """
    Enum for permission levels of a Roboto resource.
    It is a best practice to only request/use the minimum permissions required for a given operation.

    For example:
    - When listing files associated with a dataset or pulling a container image hosted in Roboto's registry,
      use `ReadOnly` permissions.
    - When adding files to a dataset or pushing a container image to Roboto's registry, use `ReadWrite` permissions.
    """

    ReadOnly = "ReadOnly"
    ReadWrite = "ReadWrite"
