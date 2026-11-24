# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Experimental Roboto APIs, whose shape and behavior may change before they become stable.

This package exports nothing: import from its subpackages, such as :py:mod:`~roboto.experimental.sessions` and
:py:mod:`~roboto.experimental.ingest`. Use these APIs to evaluate a feature and give feedback, not in long-lived
production code. When an API becomes stable, it moves to its place elsewhere under ``roboto``, and its
``roboto.experimental`` import path keeps working but issues a ``DeprecationWarning`` that names the new path. The
SDK changelog records each move and how long the old path keeps working.
"""
