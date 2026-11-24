# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from .compat import StrEnum


class RobotoRegion(StrEnum):
    """Region where Roboto stores an organization's data.

    You choose it when you create the organization, as ``data_region`` in :py:meth:`~roboto.domain.orgs.Org.create`.
    Pick the region nearest the people who upload and read the data.
    """

    US_WEST = "us-west"
    US_GOV_WEST = "us-gov-west"
    US_EAST = "us-east"
    EU_CENTRAL = "eu-central"
