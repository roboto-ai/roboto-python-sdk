# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import typing

from ....exceptions import (
    ReadPlanExecutionErrorKind,
    RobotoReadPlanExecutionException,
)
from ....time import TimeUnit
from ..read_plan import ReadPlanPartition


def plan_timestamp_unit(partition: ReadPlanPartition) -> typing.Optional[TimeUnit]:
    """Return the unit the plan gives the partition's timestamp field, or ``None`` when it gives none.

    Raises:
        RobotoReadPlanExecutionException: With kind ``unsupported-timestamp``, for a unit other than s, ms, us or ns,
            which only a plan built without validation can hold.
    """
    unit = partition.timestamp.unit
    if unit is None:
        return None
    try:
        return TimeUnit(unit)
    except ValueError:
        raise RobotoReadPlanExecutionException(
            f'The timestamp of topic partition {partition.topic_part_id} declares the unit "{unit}", '
            "which is not one of s, ms, us or ns.",
            kind=ReadPlanExecutionErrorKind.UNSUPPORTED_TIMESTAMP,
        ) from None
