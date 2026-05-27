# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import mcap_ros2.decoder

from ..._mcap_ros2_perf_patch import apply as _apply_mcap_ros2_perf_patch


def make_ros2_decoder_factory() -> mcap_ros2.decoder.DecoderFactory:
    """Build a ROS2 decoder factory with the Roboto perf patch applied.

    The patch (see :py:mod:`roboto._mcap_ros2_perf_patch`) caches the dynamically
    constructed message class per schema, which avoids rebuilding a ``SimpleNamespace``
    subclass and re-stringifying the schema definition on every message. Every consumer
    of :py:class:`mcap_ros2.decoder.DecoderFactory` in this codebase should go through
    this helper so the patch is installed before the first decode. ``apply()`` is
    idempotent and cheap on subsequent calls (a single module-attribute check).
    """
    _apply_mcap_ros2_perf_patch()
    return mcap_ros2.decoder.DecoderFactory()
