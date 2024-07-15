# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from ..command import RobotoCommandSet
from .delete_image import delete_image_command
from .delete_repo import delete_repo_command
from .list_images import ls_images_command
from .list_repos import ls_repos_command
from .login import login_command
from .pull import pull_command
from .push import push_command

commands = [
    pull_command,
    push_command,
    ls_images_command,
    ls_repos_command,
    delete_image_command,
    delete_repo_command,
    login_command,
]

command_set = RobotoCommandSet(
    name="images",
    help=("Push and pull images from Roboto's private container registry."),
    commands=commands,
)
