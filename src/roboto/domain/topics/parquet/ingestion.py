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
from ....http import RobotoClient
from ....logging import default_logger
from ....storage import FileService

logger = default_logger()


def upload_representation_file(
    file_path: pathlib.Path,
    association: Association,
    caller_org_id: typing.Optional[str] = None,
    roboto_client: typing.Optional[RobotoClient] = None,
) -> str:
    """Upload a local file to the ``.VISUALIZATION_ASSETS`` directory of a dataset and return the new file's ID.

    Roboto calls this when it ingests a CSV file. :py:meth:`~roboto.domain.topics.Topic.create_from_df` uploads a
    topic's Parquet file through it, so most code never calls it. The uploaded file keeps the local file's name.

    Args:
        file_path: Local file to upload.
        association: Dataset to upload the file to, such as ``Association.dataset("ds_12345")``.
        caller_org_id: Organization to act in. Required when the caller belongs to more than one organization;
            otherwise the caller's only organization.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.

    Returns:
        ID of the uploaded file, beginning with ``fl_``.

    Raises:
        IngestionException: The upload finished without Roboto returning an ID for the file.
        OSError: ``file_path`` cannot be read.
    """
    dest_path = pathlib.Path(".VISUALIZATION_ASSETS") / file_path.name
    file_service = FileService(roboto_client)
    completed_uploads = file_service.upload(
        [file_path],
        association,
        destination_paths={file_path: str(dest_path)},
        caller_org_id=caller_org_id,
    )

    file_id = completed_uploads.get(file_path)
    if file_id is None:
        raise IngestionException(
            f"Failed to upload visualization asset to {association.association_id}. "
            "If this error persists after retry, please reach out to Roboto support."
        )

    return file_id


def make_topic_filename_safe(name: str, replacement_char: str = "_") -> str:
    """Return ``name`` with each character that some operating systems do not allow in a filename replaced.

    Roboto calls this when it ingests a CSV file. :py:meth:`~roboto.domain.topics.Topic.create_from_df` names a
    topic's Parquet file through it, so most code never calls it. The replaced characters are ``<``, ``>``, ``:``,
    ``"``, ``/``, ``\\``, ``|``, ``?``, ``*``, and the null character.

    Args:
        name: Name to make safe, such as a topic name.
        replacement_char: String that replaces each disallowed character.

    Returns:
        ``name`` with each disallowed character replaced by ``replacement_char``.
    """
    unsafe_chars = re.compile(r'[<>:"/\\|?*\0]')
    return unsafe_chars.sub(replacement_char, name)
