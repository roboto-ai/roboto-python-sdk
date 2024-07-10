# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from ..command import RobotoCommandSet
from .create import create_command
from .delete_dataset import delete_dataset_command
from .delete_files import delete_files_command
from .download_files import download_files_command
from .list_files import list_files_command
from .search import search_command
from .show import show_command
from .update import update_command
from .upload_files import upload_files_command

commands = [
    create_command,
    delete_dataset_command,
    delete_files_command,
    download_files_command,
    list_files_command,
    show_command,
    search_command,
    update_command,
    upload_files_command,
]

command_set = RobotoCommandSet(
    name="datasets",
    help="Manage data from a single event, such a robot run or drone flight. Includes file upload and download.",
    commands=commands,
)
