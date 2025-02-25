# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime

import pydantic


class AISummary(pydantic.BaseModel):
    """
    A wire-transmissible representation of an AI summary, including the time it was created.
    """

    text: str
    created: datetime.datetime
