# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto users`` command group, which shows and deletes your user and lists the organizations you belong to.

``roboto users show`` prints your user's record as JSON, and ``roboto users orgs`` prints the record of each
organization you belong to. ``roboto users whoami`` prints, as JSON, the identity Roboto resolves when you make a
request. ``roboto users delete`` asks you to confirm, then deletes a user along with its sign-in account, organization
memberships, and personal access tokens; this cannot be undone. ``command_set`` holds the group, and
``roboto.cli.entry`` adds it to the ``roboto`` program.
"""

from .commands import command_set

__all__ = ["command_set"]
