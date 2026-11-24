# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Analysis of topic data: finding the spans of topics' data that resemble a query signal.

Use :py:func:`~roboto.analytics.signal_similarity.find_similar_signals` to search topics for a query signal; it
returns :py:class:`~roboto.analytics.signal_similarity.Match` objects, closest first, and
:py:class:`~roboto.analytics.signal_similarity.Scale` extends the search to the same pattern played faster or slower.
Requires the ``roboto[analytics]`` extra: ``pip install roboto[analytics]``.
"""

from .signal_similarity import (
    Match,
    MatchContext,
    Scale,
    find_similar_signals,
)

__all__ = ("Match", "MatchContext", "Scale", "find_similar_signals")
