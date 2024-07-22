# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import typing

import pydantic

from ..domain import datasets
from ..http import RobotoClient
from ..logging import default_logger
from ..time import utcnow
from .files import (
    UPLOAD_COMPLETE_FILENAME,
    UPLOAD_IN_PROGRESS_FILENAME,
    UploadAgentConfig,
    UploadCompleteFile,
    UploadConfigFile,
    UploadInProgressFile,
)

logger = default_logger()


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

    def run(self) -> collections.abc.Sequence[datasets.Dataset]:
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

        uploaded_datasets: list[datasets.Dataset] = []

        for upload_config_file, path in upload_config_files:
            uploaded_dataset = self.__handle_upload_config_file(
                upload_config_file, path
            )
            if uploaded_dataset is not None:
                uploaded_datasets.append(uploaded_dataset)

        return uploaded_datasets

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

    def __handle_upload_config_file(
        self, file: UploadConfigFile, path: pathlib.Path
    ) -> typing.Optional[datasets.Dataset]:
        upload_in_progress_file = path.parent / UPLOAD_IN_PROGRESS_FILENAME
        upload_complete_file = path.parent / UPLOAD_COMPLETE_FILENAME

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

        existing_dataset: typing.Optional[datasets.Dataset] = None

        if upload_in_progress_file.is_file():
            try:
                parsed_in_progress_file = UploadInProgressFile.model_validate_json(
                    upload_in_progress_file.read_text()
                )
                existing_dataset = datasets.Dataset.from_id(
                    parsed_in_progress_file.dataset_id
                )
                logger.warning(
                    "Found upload-in-progress file for dataset %s at path %s, resuming upload",
                    existing_dataset.dataset_id,
                    upload_in_progress_file.resolve(),
                )
            except pydantic.ValidationError:
                logger.warning(
                    "Couldn't parse file as a valid upload-in-progress file, ignoring: %s",
                    upload_in_progress_file,
                )

        dataset: datasets.Dataset
        if existing_dataset is None:
            logger.info("Creating a dataset for directory: %s", path.parent)
            dataset = datasets.Dataset.create(
                description=file.dataset.description,
                metadata=file.dataset.metadata,
                tags=file.dataset.tags,
                caller_org_id=file.dataset.org_id,
                roboto_client=self.__roboto_client,
            )
            logger.info("Created dataset %s for path %s", dataset.dataset_id, path)
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
        else:
            dataset = existing_dataset

        # Default to using the delete-uploaded-files strategy from the agent config file, but override it if it
        # has been explicitly set in the upload file.
        delete_uploaded_files = self.__agent_config.delete_uploaded_files
        if file.upload.delete_uploaded_files is not None:
            delete_uploaded_files = file.upload.delete_uploaded_files

        logger.info(
            "Uploading files from %s to dataset %s. Delete after upload is %s",
            path.parent,
            dataset.dataset_id,
            delete_uploaded_files,
        )

        exclude_patterns = file.upload.exclude_patterns or []
        # Explicitly opt out of uploading the upload-in-progress file.
        exclude_patterns.append(UPLOAD_IN_PROGRESS_FILENAME)

        dataset.upload_directory(
            directory_path=path.parent,
            exclude_patterns=exclude_patterns,
            delete_after_upload=delete_uploaded_files,
        )

        if path.is_file():
            logger.info("Deleting marker file %s", path)
            path.unlink()

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
        upload_in_progress_file.unlink()

        # Explicitly write the upload complete file, because it's useful as an "everything is ready" triggers signal,
        # as well as a diagnostic aid.
        dataset.upload_file(upload_complete_file, UPLOAD_COMPLETE_FILENAME)

        logger.info(
            f"Upload completed, view at https://app.roboto.ai/datasets/{dataset.dataset_id}"
        )

        return dataset
