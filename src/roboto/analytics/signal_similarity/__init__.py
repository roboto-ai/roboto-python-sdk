# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Similarity search over topic data: finding the spans of topics' messages whose shape resembles a query signal.

Use :py:func:`~roboto.analytics.signal_similarity.find_similar_signals` to search topics for a query signal, and pass
it a :py:class:`~roboto.analytics.signal_similarity.Scale` to also find the signal played faster or slower. Each result
is a :py:class:`~roboto.analytics.signal_similarity.Match`. Requires the ``roboto[analytics]`` extra:
``pip install roboto[analytics]``.
"""

from .match import Match, MatchContext, Scale
from .signal_similarity import (
    find_similar_signals,
)

__all__ = ("Match", "MatchContext", "Scale", "find_similar_signals")
