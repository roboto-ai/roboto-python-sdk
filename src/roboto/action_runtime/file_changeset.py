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
    """Change to one of an action's output files, stored as one JSON line in ``ROBOTO_FILE_METADATA_CHANGESET_FILE``.

    Each call to a method of :py:class:`~roboto.action_runtime.FilesChangesetFileManager`, such as
    :py:meth:`~roboto.action_runtime.FilesChangesetFileManager.put_tags`, appends one.
    """

    relative_path: str
    """Path of the file relative to the action's output directory, and so its path in the dataset after upload."""

    update: files.UpdateFileRecordRequest
    """Change to apply to the file once Roboto uploads it."""


class FilesChangesetFileManager:
    """Service that records tag, metadata, and description changes for an action's output files.

    An action's output files reach Roboto only after the action finishes, when Roboto uploads its output directory
    (``ROBOTO_OUTPUT_DIR``), so the action cannot change them with :py:meth:`~roboto.domain.files.File.update` while
    it runs. Each method of this class instead appends the change to the file at
    ``ROBOTO_FILE_METADATA_CHANGESET_FILE``. After the upload, Roboto applies each change to the file at the same path
    in the dataset it uploaded to, and skips paths where that dataset has no file.

    Each method can be called any number of times while the action runs, and the calls accumulate.

    Get the invocation's instance from :py:attr:`~roboto.action_runtime.InvocationContext.file_changeset_manager`.

    Note:
        When the first call for a file is ``set_description``, Roboto drops the tag and metadata changes of every
        later call for that file.

    Raises:
        ValueError: ``ROBOTO_FILE_METADATA_CHANGESET_FILE`` is not set.
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
        """Add tags to an output file once Roboto uploads it.

        Args:
            relative_path: Path of the file relative to the action's output directory.
            tags: Tags to add to the file.

        Examples:
            Tag the file the action writes to ``images/front0_raw_000734.jpg`` in its output directory:

            >>> from roboto import InvocationContext
            >>> manager = InvocationContext.from_env().file_changeset_manager
            >>> manager.put_tags("images/front0_raw_000734.jpg", ["cloudy", "rainy"])
        """
        self.__append_update(
            relative_path,
            files.UpdateFileRecordRequest(metadata_changeset=MetadataChangeset(put_tags=tags)),
        )

    def remove_tags(self, relative_path: str, tags: list[str]):
        """Remove tags from an output file once Roboto uploads it.

        Roboto applies removals before additions, so it cannot remove a tag that a ``put_tags`` call adds to the same
        file, whichever call came first.

        Args:
            relative_path: Path of the file relative to the action's output directory.
            tags: Tags to remove from the file.

        Examples:
            >>> from roboto import InvocationContext
            >>> manager = InvocationContext.from_env().file_changeset_manager
            >>> manager.remove_tags("images/front0_raw_000734.jpg", ["rainy"])
        """
        self.__append_update(
            relative_path,
            files.UpdateFileRecordRequest(metadata_changeset=MetadataChangeset(remove_tags=tags)),
        )

    def put_fields(self, relative_path: str, metadata: dict[str, typing.Any]):
        """Set key-value metadata on an output file once Roboto uploads it.

        When two calls set the same key, the later call's value wins.

        Args:
            relative_path: Path of the file relative to the action's output directory.
            metadata: Key-value metadata to set on the file.

        Examples:
            Set two keys:

            >>> from roboto import InvocationContext
            >>> manager = InvocationContext.from_env().file_changeset_manager
            >>> manager.put_fields("images/front0_raw_000734.jpg", {"cars": 2, "trucks": 3})

            Change ``cars`` and add ``planes`` with a later call:

            >>> manager.put_fields("images/front0_raw_000734.jpg", {"cars": 3, "planes": 1})
        """
        self.__append_update(
            relative_path,
            files.UpdateFileRecordRequest(metadata_changeset=MetadataChangeset(put_fields=metadata)),
        )

    def remove_fields(self, relative_path: str, keys: list[str]):
        """Remove metadata keys from an output file once Roboto uploads it.

        Roboto applies removals before additions, so it cannot remove a key that a ``put_fields`` call sets on the
        same file, whichever call came first.

        Args:
            relative_path: Path of the file relative to the action's output directory.
            keys: Metadata keys to remove from the file.

        Examples:
            >>> from roboto import InvocationContext
            >>> manager = InvocationContext.from_env().file_changeset_manager
            >>> manager.remove_fields("images/front0_raw_000734.jpg", ["trucks"])
        """
        self.__append_update(
            relative_path,
            files.UpdateFileRecordRequest(metadata_changeset=MetadataChangeset(remove_fields=keys)),
        )

    def set_description(self, relative_path: str, description: typing.Optional[str]):
        """Set the description of an output file once Roboto uploads it.

        When called more than once for a file, the last call's description wins.

        Args:
            relative_path: Path of the file relative to the action's output directory.
            description: Human-readable description of the file. ``None`` clears a description an earlier call set.

        Examples:
            >>> from roboto import InvocationContext
            >>> manager = InvocationContext.from_env().file_changeset_manager
            >>> manager.set_description("images/front0_raw_000734.jpg", "This image was over-exposed")
        """
        self.__append_update(relative_path, files.UpdateFileRecordRequest(description=description))

    def _apply_to_dataset(self, dataset: datasets.Dataset):
        """Apply the recorded changes to the files of ``dataset`` at the recorded paths.

        A path with no file in ``dataset`` is skipped. When any recorded line fails to parse, it logs the error and
        applies no changes.

        Raises:
            ValueError: ``ROBOTO_OUTPUT_DIR`` is not set.
        """
        if RobotoEnv.default().output_dir is None:
            raise ValueError(
                "Couldn't apply changes with no specified output dir via env var " + RobotoEnvKey.OutputDir
            )

        with open(self.__path, "r") as f:
            lines = f.readlines()

        try:
            items = [FilesChangesetItem.model_validate_json(line) for line in lines]
        except pydantic.ValidationError as ve:
            logger.error("Got malformed files metadata changeset file, ignoring.", exc_info=ve)
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
                if sentinels.is_set(existing_update.metadata_changeset) and sentinels.is_set(
                    item.update.metadata_changeset
                ):
                    new_update.metadata_changeset = existing_update.metadata_changeset.combine(
                        item.update.metadata_changeset
                    )

                updates_by_path[item.relative_path] = new_update

        relevant_files: list[files.File] = []

        for dataset_file in dataset.list_files():
            if dataset_file.relative_path in updates_by_path.keys():
                relevant_files.append(dataset_file)

        if len(relevant_files) == 0:
            logger.info("No file metadata update requests")
        else:
            logger.info(f"Attempting to update metadata for {len(relevant_files)} files")

        for relevant_file in relevant_files:
            update_by_path = updates_by_path[relevant_file.relative_path]
            relevant_file.update(
                description=update_by_path.description,
                metadata_changeset=update_by_path.metadata_changeset,
            )

    def __append_update(self, relative_path: str, update: files.UpdateFileRecordRequest):
        # A call that repeats an earlier change is harmless: _apply_to_dataset merges every line for a path into one
        # update.
        with open(self.__path, "a") as f:
            print(
                FilesChangesetItem(relative_path=relative_path, update=update).model_dump_json(),
                file=f,
            )
