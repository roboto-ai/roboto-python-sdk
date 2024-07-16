# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pathlib
import typing

import pydantic

from roboto import sentinels
from roboto.domain import datasets, files
from roboto.env import RobotoEnv, RobotoEnvKey
from roboto.logging import default_logger
from roboto.updates import MetadataChangeset

logger = default_logger()


class FilesChangesetItem(pydantic.BaseModel):
    """
    A single row in the file metadata changeset .jsonl file.
    """

    relative_path: str
    """The path to the file relative to the ``${ROBOTO_OUTPUT_DIR}`` directory, which will correspond to the file's
    relative_path in a roboto dataset after upload."""

    update: files.UpdateFileRecordRequest
    """The file metadata update to apply to the file."""


class FilesChangesetFileManager:
    """
    This class is used to pre-write tags/metadata updates to files which haven't been uploaded yet, but will be at the
    conclusion of an action, by virtue of being in that action's output directory.

    It uses a "file changeset" file to accumulate these pending updates during an action's runtime, and then applies
    them automatically at the end of an action, after the action's output directory has been uploaded.

    The most common way to get access to this would be via :class:`roboto.action_runtime.ActionRuntime`.
    """

    __path: pathlib.Path

    def __init__(self):
        path_str = RobotoEnv.default().file_metadata_changeset_file
        if path_str is None:
            raise ValueError(
                "Couldn't locate expected file metadata changeset file from env var "
                + RobotoEnvKey.FileMetadataChangesetFile
            )

        path = pathlib.Path(path_str)
        if not path.exists():
            path.touch()

        self.__path = path

    def put_tags(self, relative_path: str, tags: list[str]):
        """
        Adds tags to a to-be-uploaded file which is expected to be written to
        ``${ROBOTO_OUTPUT_DIR}/relative_path`` by the end of the user portion of an action's runtime.

        This can be called multiple times throughout the runtime of an action, and will be accumulated accordingly.
        Order of calls matters.

        Examples:
            >>> from roboto import ActionRuntime
            >>> action_runtime = ActionRuntime.from_env()
            >>> file_changeset_manager = action_runtime.file_changeset_manager
            >>>
            >>> # This would reference a file at ${ROBOTO_OUTPUT_DIR}/images/front0_raw_000734.jpg
            >>> file_changeset_manager.put_tags("images/front0_raw_000734.jpg", ["cloudy", "rainy"]})
        """
        self.__append_update(
            relative_path,
            files.UpdateFileRecordRequest(
                metadata_changeset=MetadataChangeset(put_tags=tags)
            ),
        )

    def remove_tags(self, relative_path: str, tags: list[str]):
        """
        Removes tags from a to-be-uploaded file which is expected to be written to
        ``${ROBOTO_OUTPUT_DIR}/relative_path`` by the end of the user portion of an action's runtime. You'll generally
        only need this to remove tags which were added by a previous call to :meth:`put_tags`.

        This can be called multiple times throughout the runtime of an action, and will be accumulated accordingly.
        Order of calls matters.

        Examples:
            >>> from roboto import ActionRuntime
            >>> action_runtime = ActionRuntime.from_env()
            >>> file_changeset_manager = action_runtime.file_changeset_manager
            >>>
            >>> # This would reference a file at ${ROBOTO_OUTPUT_DIR}/images/front0_raw_000734.jpg
            >>> file_changeset_manager.put_tags("images/front0_raw_000734.jpg", ["cloudy", "rainy"]})
            >>>
            >>> # Actually this is just Seattle's aggressive mist, that's not really rainy...
            >>> file_changeset_manager.remove_tags("images/front0_raw_000734.jpg", ["rainy"]})
        """
        self.__append_update(
            relative_path,
            files.UpdateFileRecordRequest(
                metadata_changeset=MetadataChangeset(remove_tags=tags)
            ),
        )

    def put_fields(self, relative_path: str, metadata: dict[str, typing.Any]):
        """
        Adds metadata key/value pairs to a to-be-uploaded file which is expected to be written to
        ``${ROBOTO_OUTPUT_DIR}/relative_path`` by the end of the user portion of an action's runtime.

        This can be called multiple times throughout the runtime of an action, and will be accumulated accordingly.
        Order of calls matters.

        Examples:
            >>> from roboto import ActionRuntime
            >>> action_runtime = ActionRuntime.from_env()
            >>> file_changeset_manager = action_runtime.file_changeset_manager
            >>>
            >>> # This would reference a file at ${ROBOTO_OUTPUT_DIR}/images/front0_raw_000734.jpg
            >>> file_changeset_manager.put_fields("images/front0_raw_000734.jpg", {"cars": 2, "trucks": 3})
            >>>
            >>> # Actually there was a 3rd car I missed in the first pass, and a plane, let me fix that...
            >>> file_changeset_manager.put_fields("images/front0_raw_000734.jpg", {"cars": 3, "planes": 1})
        """
        self.__append_update(
            relative_path,
            files.UpdateFileRecordRequest(
                metadata_changeset=MetadataChangeset(put_fields=metadata)
            ),
        )

    def remove_fields(self, relative_path: str, keys: list[str]):
        """
        Removes metadata key/value pairs from a to-be-uploaded file which is expected to be written to
        ``${ROBOTO_OUTPUT_DIR}/relative_path`` by the end of the user portion of an action's runtime. You'll generally
        only need this to remove values which were added by a previous call to :meth:`put_fields`.

        This can be called multiple times throughout the runtime of an action, and will be accumulated accordingly.
        Order of calls matters.

        Examples:
            >>> from roboto import ActionRuntime
            >>> action_runtime = ActionRuntime.from_env()
            >>> file_changeset_manager = action_runtime.file_changeset_manager
            >>>
            >>> # This would reference a file at ${ROBOTO_OUTPUT_DIR}/images/front0_raw_000734.jpg
            >>> file_changeset_manager.put_fields("images/front0_raw_000734.jpg", {"cars": 2, "trucks": 3})
            >>>
            >>> # Whoops, actually I don't want to count those trucks...
            >>> file_changeset_manager.remove_fields("images/front0_raw_000734.jpg", ["trucks"])
        """
        self.__append_update(
            relative_path,
            files.UpdateFileRecordRequest(
                metadata_changeset=MetadataChangeset(remove_fields=keys)
            ),
        )

    def set_description(self, relative_path: str, description: typing.Optional[str]):
        """
        Sets the human-readable description of a to-be-uploaded file which is expected to be written to
        ``${ROBOTO_OUTPUT_DIR}/relative_path`` by the end of the user portion of an action's runtime.

        Examples:
            >>> from roboto import ActionRuntime
            >>> action_runtime = ActionRuntime.from_env()
            >>> file_changeset_manager = action_runtime.file_changeset_manager
            >>>
            >>> # This would reference a file at ${ROBOTO_OUTPUT_DIR}/images/front0_raw_000734.jpg
            >>> file_changeset_manager.set_description("images/front0_raw_000734.jpg", "This image was over-exposed")
        """
        self.__append_update(
            relative_path, files.UpdateFileRecordRequest(description=description)
        )

    def _apply_to_dataset(self, dataset: datasets.Dataset):
        """
        Applies all pending file metadata changes to the given dataset. This is what the Roboto action framework
        calls after the user portion of an action's runtime has completed. You should never need to call this directly.
        """
        if RobotoEnv.default().output_dir is None:
            raise ValueError(
                "Couldn't apply changes with no specified output dir via env var "
                + RobotoEnvKey.OutputDir
            )

        with open(self.__path, "r") as f:
            lines = f.readlines()

        try:
            items = [FilesChangesetItem.model_validate_json(line) for line in lines]
        except pydantic.ValidationError as ve:
            logger.error(
                "Got malformed files metadata changeset file, ignoring.", exc_info=ve
            )
            return

        updates_by_path: dict[str, files.UpdateFileRecordRequest] = {}

        for item in items:
            existing_update = updates_by_path.get(item.relative_path)

            if existing_update is None:
                updates_by_path[item.relative_path] = item.update
            else:
                new_update = existing_update

                if sentinels.is_set(item.update.description):
                    new_update.description = item.update.description
                if sentinels.is_set(
                    existing_update.metadata_changeset
                ) and sentinels.is_set(item.update.metadata_changeset):
                    new_update.metadata_changeset = (
                        existing_update.metadata_changeset.combine(
                            item.update.metadata_changeset
                        )
                    )

                updates_by_path[item.relative_path] = new_update

        relevant_files: list[files.File] = []

        for dataset_file in dataset.list_files():
            if dataset_file.relative_path in updates_by_path.keys():
                relevant_files.append(dataset_file)

        if len(relevant_files) == 0:
            logger.info("No file metadata update requests")
        else:
            logger.info(
                f"Attempting to update metadata for {len(relevant_files)} files"
            )

        for relevant_file in relevant_files:
            update_by_path = updates_by_path[relevant_file.relative_path]
            relevant_file.update(
                description=update_by_path.description,
                metadata_changeset=update_by_path.metadata_changeset,
            )

    def __append_update(
        self, relative_path: str, update: files.UpdateFileRecordRequest
    ):
        # Duplicates are OK, as we'll ignore them at upload time
        with open(self.__path, "a") as f:
            print(
                FilesChangesetItem(
                    relative_path=relative_path, update=update
                ).model_dump_json(),
                file=f,
            )
