# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import atexit
import collections.abc
import concurrent.futures
import contextlib
import pathlib
import time
import typing
import urllib.request

from ...association import AssociationType
from ...http import RobotoClient
from ...logging import default_logger
from ...time import Time, to_epoch_nanoseconds
from .mcap_reader import McapReader
from .operations import (
    MessagePathRepresentationMapping,
)
from .record import (
    MessagePathRecord,
    RepresentationRecord,
    RepresentationStorageFormat,
)

logger = default_logger()

OUTFILE_NAME_PATTERN = "{repr_id}_{file_id}.mcap"


class TopicDataService:
    """
    Data service that extracts common logic for retrieving topic data ingested by Roboto.
    This is not intended as a public API. To access topic data,
    prefer :py:meth:`~roboto.domain.topics.Topic.get_data` instead.
    """

    DEFAULT_CACHE_DIR: typing.ClassVar[pathlib.Path] = (
        pathlib.Path.home() / ".cache" / "roboto" / "topic-data"
    )

    __cache_dir: pathlib.Path
    __roboto_client: RobotoClient

    @staticmethod
    def garbage_collect_old_topic_data(
        cache_dir: pathlib.Path,
        expire_after_ns: int = 7
        * 24
        * 60
        * 60
        * 100
        * 1_000_000,  # 7 days in nanoseconds
    ):
        pattern_as_glob = OUTFILE_NAME_PATTERN.format(file_id="*", repr_id="*")
        now_in_nanoseconds = time.time_ns()
        for mcap_file in cache_dir.glob(f"**/{pattern_as_glob}"):
            if (now_in_nanoseconds - mcap_file.stat().st_atime_ns) > expire_after_ns:
                mcap_file.unlink()

    def __init__(
        self,
        roboto_client: RobotoClient,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ):
        self.__roboto_client = roboto_client
        self.__cache_dir = (
            pathlib.Path(cache_dir)
            if cache_dir is not None
            else TopicDataService.DEFAULT_CACHE_DIR
        )

    def get_data(
        self,
        topic_id: str,
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir_override: typing.Union[str, pathlib.Path, None] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        cache_dir = (
            pathlib.Path(cache_dir_override)
            if cache_dir_override is not None
            else self.__cache_dir
        )
        if not cache_dir.exists():
            cache_dir.mkdir(parents=True)

        message_path_repr_mappings_response = self.__roboto_client.get(
            f"v1/topics/id/{topic_id}/message-path/representations/{RepresentationStorageFormat.MCAP.value}"
        )
        message_path_repr_mappings = message_path_repr_mappings_response.to_record_list(
            MessagePathRepresentationMapping
        )

        # Exclude a MessagePathRepresentationMapping if no message paths remain after applying message path filters.
        message_path_repr_mappings = [
            message_path_repr_map.model_copy(
                update={
                    "message_paths": self.__filter_message_paths(
                        message_path_repr_map.message_paths,
                        include_paths=message_paths_include,
                        exclude_paths=message_paths_exclude,
                    )
                }
            )
            for message_path_repr_map in message_path_repr_mappings
        ]
        message_path_repr_mappings = [
            message_path_repr_map
            for message_path_repr_map in message_path_repr_mappings
            if message_path_repr_map.message_paths
        ]

        repr_id_to_outfile_map: dict[str, pathlib.Path] = {}
        download_list: list[MessagePathRepresentationMapping] = []
        for message_path_repr_map in message_path_repr_mappings:
            representation = message_path_repr_map.representation
            outfile = self.__representation_out_file(
                representation, cache_dir=cache_dir
            )
            repr_id_to_outfile_map[representation.representation_id] = outfile
            if not outfile.exists():
                association = representation.association
                if association.association_type != AssociationType.File:
                    logger.warning(
                        "Unable to get data for message paths %r",
                        [
                            record.message_path
                            for record in message_path_repr_map.message_paths
                        ],
                    )
                    continue
                download_list.append(message_path_repr_map)

        if download_list:
            self.__download_representations(
                message_path_repr_mappings=download_list,
                repr_id_to_outfile_map=repr_id_to_outfile_map,
                cache_dir=cache_dir,
            )

        normalized_start_time = (
            to_epoch_nanoseconds(start_time) if start_time is not None else None
        )
        normalized_end_time = (
            to_epoch_nanoseconds(end_time) if end_time is not None else None
        )

        with contextlib.ExitStack() as exit_stack:
            readers = [
                McapReader(
                    stream=exit_stack.enter_context(
                        repr_id_to_outfile_map[
                            message_path_repr_map.representation.representation_id
                        ].open(mode="rb")
                    ),
                    message_paths=message_path_repr_map.message_paths,
                    start_time=normalized_start_time,
                    end_time=normalized_end_time,
                )
                for message_path_repr_map in message_path_repr_mappings
            ]
            while any(reader.has_next for reader in readers):
                full_record = {}
                next_earliest_timestamp = min(
                    reader.next_timestamp for reader in readers
                )
                full_record["log_time"] = next_earliest_timestamp
                for reader in readers:
                    if reader.next_message_is_time_aligned(next_earliest_timestamp):
                        decoded_message = reader.next()
                        if decoded_message is None:
                            continue
                        full_record.update(decoded_message.to_dict())

                yield full_record

    def __download_representations(
        self,
        message_path_repr_mappings: collections.abc.Sequence[
            MessagePathRepresentationMapping
        ],
        repr_id_to_outfile_map: collections.abc.Mapping[str, pathlib.Path],
        cache_dir: pathlib.Path,
    ) -> None:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_representation_mapping = {
                executor.submit(
                    self.__download_roboto_file,
                    message_path_repr_map.representation,
                    repr_id_to_outfile_map[
                        message_path_repr_map.representation.representation_id
                    ],
                ): message_path_repr_map
                for message_path_repr_map in message_path_repr_mappings
            }
            for future in concurrent.futures.as_completed(
                future_to_representation_mapping
            ):
                message_path_repr_map = future_to_representation_mapping[future]
                try:
                    future.result()
                except Exception:
                    logger.exception(
                        "Unable to get data for message paths %r",
                        [
                            record.message_path
                            for record in message_path_repr_map.message_paths
                        ],
                    )

        # Schedule a cleanup of the cache_dir to remove any old assets.
        atexit.register(
            TopicDataService.garbage_collect_old_topic_data, cache_dir=cache_dir
        )

    def __download_roboto_file(
        self,
        representation: RepresentationRecord,
        outfile: pathlib.Path,
    ) -> None:
        file_id = representation.association.association_id
        logger.debug("Getting signed url for file '%s'", file_id)
        signed_url_response = self.__roboto_client.get(f"v1/files/{file_id}/signed-url")
        signed_url = signed_url_response.to_dict(json_path=["data", "url"])

        logger.debug("Downloading file '%s' to %s", file_id, outfile)
        urllib.request.urlretrieve(signed_url, str(outfile))

    def __filter_message_paths(
        self,
        seq: collections.abc.Sequence[MessagePathRecord],
        include_paths: typing.Optional[collections.abc.Sequence[str]],
        exclude_paths: typing.Optional[collections.abc.Sequence[str]],
    ) -> collections.abc.Sequence[MessagePathRecord]:
        if not include_paths and not exclude_paths:
            return seq

        filtered = []
        include_paths_set = set(include_paths or [])
        exclude_paths_set = set(exclude_paths or [])
        for message_path_record in seq:
            message_path_parts = message_path_record.message_path.split(".")
            message_path_parents = set(
                ".".join(message_path_parts[:i])
                for i in range(len(message_path_parts), 0, -1)
            )

            if include_paths and message_path_parents.isdisjoint(include_paths_set):
                continue

            if exclude_paths and not message_path_parents.isdisjoint(exclude_paths_set):
                continue

            filtered.append(message_path_record)

        return filtered

    def __representation_out_file(
        self,
        representation: RepresentationRecord,
        cache_dir: pathlib.Path,
    ) -> pathlib.Path:
        return cache_dir / OUTFILE_NAME_PATTERN.format(
            repr_id=representation.representation_id,
            file_id=representation.association.association_id,
        )
