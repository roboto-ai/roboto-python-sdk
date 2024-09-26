# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import dataclasses
import typing

if typing.TYPE_CHECKING:
    import numpy.typing  # pants: no-infer-dep


@dataclasses.dataclass(frozen=True)
class Match:
    """
    A subsequence of a target signal that is similar to a query signal.
    """

    start_idx: int
    """
    The start index in the target signal of this match.
    """

    end_idx: int
    """
    The end index in the target signal of this match.
    """

    distance: float
    """
    Unitless measure of similarity between a query signal
    and the subsequence of the target signal this Match represents.
    A smaller distance relative to a larger distance indicates a "closer" match.
    """

    subsequence: numpy.typing.NDArray
    """
    The subsequence of the target signal this Match represents.
    It is equivalent to ``target_sequence[start_idx:end_idx]``.
    """
