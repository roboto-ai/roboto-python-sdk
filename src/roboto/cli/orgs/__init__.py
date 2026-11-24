# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto orgs`` command group, which creates, shows, and deletes organizations and manages their members.

``members`` lists an organization's members; ``invite-user``, ``list-invites`` and ``remove-user`` invite people, list
pending invitations, and remove members; and ``add-role`` and ``remove-role`` change a member's role.
``bind-email-domain`` binds an email domain, so people who sign up with an address at it join the organization, or
starts a verification of the domain where Roboto requires one. ``register-bucket`` registers an S3 bucket in your AWS
account to store the files of new datasets. ``command_set`` holds the group, and ``roboto.cli.entry`` adds it to
the ``roboto`` program.
"""

from .commands import command_set

__all__ = ["command_set"]
