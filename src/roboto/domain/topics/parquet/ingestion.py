# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import pathlib
import re
import typing

from ....association import Association
from ....exceptions import IngestionException
from ....file_infra import FileService
from ....http import RobotoClient
from ....logging import default_logger

logger = default_logger()


def upload_representation_file(
    file_path: pathlib.Path,
    association: Association,
    caller_org_id: typing.Optional[str] = None,
    roboto_client: typing.Optional[RobotoClient] = None,
) -> str:
    dest_path = pathlib.Path(".VISUALIZATION_ASSETS") / file_path.name
    file_service = FileService(roboto_client)
    file_ids = file_service.upload(
        [file_path],
        association,
        destination_paths={file_path: str(dest_path)},
        caller_org_id=caller_org_id,
    )

    if not file_ids:
        raise IngestionException(
            f"Failed to upload visualization asset to {association.association_id}. "
            "If this error persists after retry, please reach out to Roboto support."
        )

    return file_ids[0]


def make_topic_filename_safe(name: str, replacement_char: str = "_") -> str:
    unsafe_chars = re.compile(r'[<>:"/\\|?*\0]')
    return unsafe_chars.sub(replacement_char, name)
