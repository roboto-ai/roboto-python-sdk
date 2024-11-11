# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum


class RobotoRegion(str, enum.Enum):
    """
    The geographic region of a Roboto resource. Used when configuring org-level default behavior for data storage, in
    order to ensure that data is close to your users.
    """

    US_WEST = "us-west"
    US_GOV_WEST = "us-gov-west"
    US_EAST = "us-east"
    EU_CENTRAL = "eu-central"
