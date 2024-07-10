# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


def safe_access_array(array, index):
    if array is not None and isinstance(array, list) and len(array) > index:
        return array[index]
    return None
