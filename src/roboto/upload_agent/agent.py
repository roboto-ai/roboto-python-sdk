# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import typing

import pydantic

from ..config import DEFAULT_ROBOTO_DIR
from ..domain import datasets
from ..env import resolve_env_variables
from ..http import RobotoClient
from ..logging import default_logger
from ..time import utcnow
from ..updates import MetadataChangeset
from .files import (
    UPLOAD_COMPLETE_FILENAME,
    UPLOAD_IN_PROGRESS_FILENAME,
    UploadAgentConfig,
    UploadCompleteFile,
    UploadConfigFile,
    UploadInProgressFile,
)

logger = default_logger()


DEFAULT_ROBOTO_UPLOAD_FILE = DEFAULT_ROBOTO_DIR / "default_roboto_upload.json"
"""If you put a template JSON file here, it'll be used by `:func:`~create_upload_configs`"""


class UploadAgent:
    __roboto_client: RobotoClient
    __agent_config: UploadAgentConfig

    def __init__(
        self,
        agent_config: UploadAgentConfig,
        roboto_client: typing.Optional[RobotoClient] = None,
    ):
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__agent_config = agent_config

    def create_upload_configs(self):
        directories_to_consider: list[pathlib.Path] = []

        for search_path in self.__agent_config.search_paths:
            if not search_path.is_dir():
                continue

            directories_to_consider.extend(
                [subdir for subdir in search_path.iterdir() if subdir.is_dir()]
            )

        upload_config_file_contents = UploadConfigFile()
        if DEFAULT_ROBOTO_UPLOAD_FILE.is_file():
            try:
                upload_config_file_contents = UploadConfigFile.model_validate_json(
                    resolve_env_variables(DEFAULT_ROBOTO_UPLOAD_FILE.read_text())
                )
                logger.info(
                    "Successfully loaded default config file %s, using it for new uploads.",
                    DEFAULT_ROBOTO_UPLOAD_FILE,
                )
            except Exception:
                logger.warning(
                    "Couldn't parse default config file at %s, using blank contents '{}' instead.",
                    DEFAULT_ROBOTO_UPLOAD_FILE,
                )
        else:
            logger.info(
                "No default upload config file found at %s, using blank contents '{}' instead.",
                DEFAULT_ROBOTO_UPLOAD_FILE,
            )

        for subdir in directories_to_consider:
            if len(list(subdir.iterdir())) == 0:
                logger.info("Directory %s is empty, skipping", subdir)
                continue

            upload_config_file = subdir / self.__agent_config.upload_config_filename
            if upload_config_file.is_file():
                logger.info(
                    "Directory %s already has an upload config file, skipping", subdir
                )
                continue

            upload_in_progress_file = subdir / UPLOAD_IN_PROGRESS_FILENAME
            if upload_in_progress_file.is_file():
                logger.info(
                    "Directory %s has an upload in progress file, skipping", subdir
                )
                continue

            upload_complete_file = subdir / UPLOAD_COMPLETE_FILENAME
            if upload_complete_file.is_file():
                logger.info(
                    "Directory %s has an upload completed file, skipping", subdir
                )
                continue

            upload_config_file.write_text(
                upload_config_file_contents.model_dump_json(indent=2)
            )
            logger.info("Wrote upload config file to %s", upload_config_file)

    def process_uploads(
        self, merge_uploads: bool = False
    ) -> collections.abc.Sequence[datasets.Dataset]:
        """
        If merge is true, everything will be combined into a single dataset. Otherwise, each directory will be uploaded
        to a separate dataset.
        """

        upload_config_files = self.__get_upload_config_files()
        if len(upload_config_files) == 0:
            logger.info(
                "No upload config files found under any search path, nothing to do."
            )
            return []
        else:
            logger.info(
                "Found %d total upload config files across all search paths, starting uploads.",
                len(upload_config_files),
            )

        update_dataset: typing.Optional[datasets.Dataset] = None
        created_datasets: list[datasets.Dataset] = []

        if merge_uploads:
            update_dataset = datasets.Dataset.create(
                roboto_client=self.__roboto_client,
                caller_org_id=self.__agent_config.default_org_id,
            )

            created_datasets.append(update_dataset)

        for upload_config_file, path in upload_config_files:
            uploaded_dataset = self.__handle_upload_config_file(
                file=upload_config_file, path=path, update_dataset=update_dataset
            )
            if uploaded_dataset is not None:
                created_datasets.append(uploaded_dataset)

        return created_datasets

    def __get_upload_config_files(
        self,
    ) -> collections.abc.Collection[tuple[UploadConfigFile, pathlib.Path]]:
        upload_config_files: list[tuple[UploadConfigFile, pathlib.Path]] = []

        for search_path in self.__agent_config.search_paths:
            if not search_path.is_dir():
                logger.error("Search path is not a directory: %s", search_path)
                continue

            found = 0

            logger.info("Scanning '%s' for upload config files", search_path)
            for upload_config_file in search_path.rglob(
                self.__agent_config.upload_config_filename
            ):
                try:
                    parsed_file = UploadConfigFile.model_validate_json(
                        upload_config_file.read_text()
                    )

                    logger.info("Found upload config file: %s", upload_config_file)
                    upload_config_files.append((parsed_file, upload_config_file))
                    found += 1
                except pydantic.ValidationError as exc:
                    logger.error(
                        "Couldn't parse file as valid upload config files: %s",
                        upload_config_file,
                        exc_info=exc,
                    )

            if found == 0:
                logger.info(
                    "No upload config files found for search path: %s", search_path
                )
            else:
                logger.info(
                    "Found %d upload config files under search path: %s",
                    found,
                    search_path,
                )

        return upload_config_files

    def __delete_uploaded_dir_if_safe(self, path: pathlib.Path):
        if not path.is_dir():
            return

        files = [f for f in path.iterdir()]

        if len(files) > 1:
            return

        if len(files) == 1:
            if files[0].name != UPLOAD_COMPLETE_FILENAME:
                return

            files[0].unlink(missing_ok=True)

        path.rmdir()

        logger.info("Cleaned up empty upload directory %s", path)

    def __handle_upload_config_file(
        self,
        file: UploadConfigFile,
        path: pathlib.Path,
        update_dataset: typing.Optional[datasets.Dataset] = None,
    ) -> typing.Optional[datasets.Dataset]:
        """
        If you pass in an update_dataset, it will be used instead of creating a new one, and any
        dataset properties in the upload config file will be applied as an update.

        This will return a dataset if one is created, which means it will NOT return a dataset passed into the
        ``update_dataset`` param.
        """
        dir_to_upload = path.parent

        upload_in_progress_file = dir_to_upload / UPLOAD_IN_PROGRESS_FILENAME
        upload_complete_file = dir_to_upload / UPLOAD_COMPLETE_FILENAME

        if upload_complete_file.is_file():
            try:
                parsed_complete_file = UploadCompleteFile.model_validate_json(
                    upload_complete_file.read_text()
                )
                logger.info(
                    "Found upload-complete file for dataset %s at path %s, skipping upload",
                    parsed_complete_file.dataset_id,
                    upload_complete_file.resolve(),
                )
            except pydantic.ValidationError:
                logger.warning(
                    "Couldn't parse file as a valid upload-complete file. Still ignoring upload to be safe, but "
                    + "it might not have worked: %s",
                    upload_in_progress_file,
                )

            return None

        in_progress_dataset: typing.Optional[datasets.Dataset] = None

        if upload_in_progress_file.is_file():
            try:
                parsed_in_progress_file = UploadInProgressFile.model_validate_json(
                    upload_in_progress_file.read_text()
                )
                in_progress_dataset = datasets.Dataset.from_id(
                    parsed_in_progress_file.dataset_id
                )
                logger.warning(
                    "Found upload-in-progress file for dataset %s at path %s, resuming upload",
                    in_progress_dataset.dataset_id,
                    upload_in_progress_file.resolve(),
                )
            except pydantic.ValidationError:
                logger.warning(
                    "Couldn't parse file as a valid upload-in-progress file, ignoring: %s",
                    upload_in_progress_file,
                )

        dataset: datasets.Dataset
        should_write_in_progress_file: bool

        # Order of figuring out what dataset we're working on:
        # 1. In progress is always the first choice, because if it exists, it means we already made a decision that
        #    we want to stick with, and for some reason the upload failed. Let's not change that.
        # 2. Explicit update
        # 3. Create new
        if in_progress_dataset is not None:
            dataset = in_progress_dataset
            should_write_in_progress_file = False

        elif update_dataset is not None:
            logger.info(
                "Applying update to existing dataset %s for directory: %s",
                update_dataset.dataset_id,
                dir_to_upload,
            )
            dataset = update_dataset
            dataset.update(
                description=file.dataset.description,
                metadata_changeset=MetadataChangeset(
                    put_fields=file.dataset.metadata,
                    put_tags=file.dataset.tags,
                ),
            )
            logger.info("Successfully updated dataset %s", dataset.dataset_id)
            should_write_in_progress_file = True

        else:
            logger.info("Creating a dataset for directory: %s", dir_to_upload)
            dataset = datasets.Dataset.create(
                description=file.dataset.description,
                metadata=file.dataset.metadata,
                tags=file.dataset.tags,
                caller_org_id=file.dataset.org_id,
                roboto_client=self.__roboto_client,
            )
            logger.info("Created dataset %s for path %s", dataset.dataset_id, path)
            should_write_in_progress_file = True

        if should_write_in_progress_file:
            logger.debug(
                "Writing in progress file to %s", upload_in_progress_file.resolve()
            )
            upload_in_progress_file.write_text(
                UploadInProgressFile(
                    version="v1",
                    dataset_id=dataset.dataset_id,
                    started=dataset.record.created,
                ).model_dump_json(indent=2)
            )

        # Default to using the delete-uploaded-files strategy from the agent config file, but override it if it
        # has been explicitly set in the upload file.
        delete_uploaded_files = self.__agent_config.delete_uploaded_files
        if file.upload.delete_uploaded_files is not None:
            delete_uploaded_files = file.upload.delete_uploaded_files

        logger.info(
            "Uploading files from %s to dataset %s. Delete after upload is %s",
            dir_to_upload,
            dataset.dataset_id,
            delete_uploaded_files,
        )

        exclude_patterns = file.upload.exclude_patterns or []
        # Explicitly opt out of uploading the upload-in-progress file.
        exclude_patterns.append(f"**/{UPLOAD_IN_PROGRESS_FILENAME}")

        dataset.upload_directory(
            directory_path=dir_to_upload,
            exclude_patterns=exclude_patterns,
            include_patterns=file.upload.include_patterns,
            delete_after_upload=delete_uploaded_files,
        )

        if path.is_file():
            logger.info("Deleting marker file %s", path)
            path.unlink(missing_ok=True)

        logger.debug(
            "Writing upload complete file to %s", upload_complete_file.resolve()
        )
        upload_complete_file.write_text(
            UploadCompleteFile(
                version="v1", dataset_id=dataset.dataset_id, completed=utcnow()
            ).model_dump_json(indent=2)
        )

        # Delete the in progress file after writing the complete file, because that's when we know for sure that
        # our completion has been signaled to both Roboto service and the local OS.
        upload_in_progress_file.unlink(missing_ok=True)

        # Explicitly write the upload complete file, because it's useful as an "everything is ready" triggers signal,
        # as well as a diagnostic aid.
        dataset.upload_file(upload_complete_file, UPLOAD_COMPLETE_FILENAME)

        logger.info(
            f"Upload completed, view at {self.__roboto_client.frontend_endpoint}/datasets/{dataset.dataset_id}"
        )

        if self.__agent_config.delete_empty_directories:
            self.__delete_uploaded_dir_if_safe(dir_to_upload)

        # If we were passed in an update_dataset, we don't want to return it, because the intention of the return
        # is to be added to an array of created datasets. This one already exists / wasn't created by this call.
        if update_dataset is not None:
            return None

        return dataset
