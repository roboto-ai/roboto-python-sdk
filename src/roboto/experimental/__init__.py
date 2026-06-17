# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Roboto APIs in active refinement.

Importing from ``roboto.experimental`` is your acknowledgement that the
imported API may change in shape, behavior, or semantics before it
stabilizes. Use these APIs for evaluation and feedback, not for
long-lived production code.

When an API graduates to stable, it moves to its canonical ``roboto.*``
location, and its ``roboto.experimental`` import path becomes a
forwarding alias that emits a ``DeprecationWarning`` advising you to
update the import. The CHANGELOG records each graduation and the
alias's lifetime.
"""
