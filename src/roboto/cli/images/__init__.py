# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto images`` command group, which pushes and pulls the container images that actions run in.

``roboto images push`` uploads a local amd64 image to Roboto's image registry, creating its repository if needed, and
``roboto images pull`` downloads one; both sign Docker in to the registry first, so they need the Docker CLI. The
group's other commands list and delete images and repositories, and ``roboto images login`` signs Docker in to one
repository with temporary credentials. ``command_set`` holds the group, and ``roboto.cli.entry`` adds it to the
``roboto`` program.
"""

from .commands import command_set

__all__ = ("command_set",)
