# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto triggers`` command group, which creates, lists, shows, updates, enables, disables, and deletes triggers.

A trigger is a rule that runs its targets, which invoke an action, start an agent, or send a Slack message, on the
platform events it subscribes to that match its optional condition, or on a cron schedule.
``roboto triggers dry-run`` reports, gate by gate, whether a trigger would fire for a platform event about a dataset,
file, invocation, or event, or at a minute of its schedule, without running any target. ``roboto triggers sample``
prints a sample platform event of one type and the values a condition or target template can reference.
``command_set`` holds the group, and ``roboto.cli.entry`` adds it to the ``roboto`` program.
"""

from .commands import command_set

__all__ = ["command_set"]
