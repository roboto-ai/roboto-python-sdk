# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import atexit
import collections.abc
import concurrent.futures
import contextlib
import datetime
import logging
import pathlib
import time
import typing
import urllib.request

from ...association import AssociationType
from ...compat import import_optional_dependency
from ...http import RobotoClient
from ...logging import default_logger
from .mcap_reader import McapReader
from .operations import (
    MessagePathRepresentationMapping,
)
from .record import (
    RepresentationRecord,
    RepresentationStorageFormat,
)
from .topic_reader import TopicReader

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep

logger = default_logger()

OUTFILE_NAME_PATTERN = "{repr_id}_{file_id}.mcap"


def garbage_collect_old_topic_data(
    cache_dir: pathlib.Path,
    expire_after: datetime.timedelta = datetime.timedelta(days=7),
):
    pattern_as_glob = OUTFILE_NAME_PATTERN.format(file_id="*", repr_id="*")
    now_in_nanoseconds = time.time_ns()
    expire_after_ns = int(expire_after.total_seconds() * 1_000_000_000)
    for mcap_file in cache_dir.glob(f"**/{pattern_as_glob}"):
        if (now_in_nanoseconds - mcap_file.stat().st_atime_ns) > expire_after_ns:
            mcap_file.unlink()


class McapTopicReader(TopicReader):
    __cache_dir: pathlib.Path
    __roboto_client: RobotoClient

    @staticmethod
    def accepts(
        message_paths_to_representations: collections.abc.Iterable[
            MessagePathRepresentationMapping
        ],
    ) -> bool:
        for mapping in message_paths_to_representations:
            if (
                mapping.representation.storage_format
                != RepresentationStorageFormat.MCAP
            ):
                return False
        return True

    def __init__(self, roboto_client: RobotoClient, cache_dir: pathlib.Path):
        self.__roboto_client = roboto_client
        self.__cache_dir = cache_dir

    def get_data(
        self,
        message_paths_to_representations: collections.abc.Iterable[
            MessagePathRepresentationMapping
        ],
        log_time_attr_name: str,
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        # Schedule a cleanup of the cache_dir to remove any old assets.
        atexit.register(garbage_collect_old_topic_data, cache_dir=self.__cache_dir)

        repr_id_to_outfile_map = self.__ensure_cached(message_paths_to_representations)

        with contextlib.ExitStack() as exit_stack:
            readers = [
                McapReader(
                    stream=exit_stack.enter_context(
                        repr_id_to_outfile_map[
                            message_path_repr_map.representation.representation_id
                        ].open(mode="rb")
                    ),
                    message_paths=message_path_repr_map.message_paths,
                    start_time=start_time,
                    end_time=end_time,
                )
                for message_path_repr_map in message_paths_to_representations
            ]

            if logger.isEnabledFor(logging.DEBUG):
                for reader in readers:
                    logger.debug(
                        "Reader will pick %r message_paths from data",
                        reader.message_paths,
                    )

            while any(reader.has_next for reader in readers):
                full_record = {}
                next_earliest_timestamp = min(
                    reader.next_timestamp for reader in readers
                )
                full_record[log_time_attr_name] = next_earliest_timestamp
                for reader in readers:
                    if reader.next_message_is_time_aligned(next_earliest_timestamp):
                        decoded_message = reader.next()
                        if decoded_message is None:
                            continue
                        full_record.update(decoded_message.to_dict())

                yield full_record

    def get_data_as_df(
        self,
        message_paths_to_representations: collections.abc.Iterable[
            MessagePathRepresentationMapping
        ],
        log_time_attr_name: str,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> "pandas.DataFrame":
        pd = import_optional_dependency("pandas", "analytics")

        return pd.json_normalize(
            data=list(
                self.get_data(
                    message_paths_to_representations=message_paths_to_representations,
                    log_time_attr_name=log_time_attr_name,
                    start_time=start_time,
                    end_time=end_time,
                )
            )
        )

    def __ensure_cached(
        self,
        message_paths_to_representations: collections.abc.Iterable[
            MessagePathRepresentationMapping
        ],
    ) -> dict[str, pathlib.Path]:
        repr_id_to_outfile_map: dict[str, pathlib.Path] = {}
        download_list: list[MessagePathRepresentationMapping] = []
        for message_path_repr_map in message_paths_to_representations:
            representation = message_path_repr_map.representation
            outfile = self.__representation_out_file(
                representation, cache_dir=self.__cache_dir
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
            )

        return repr_id_to_outfile_map

    def __download_representations(
        self,
        message_path_repr_mappings: collections.abc.Sequence[
            MessagePathRepresentationMapping
        ],
        repr_id_to_outfile_map: collections.abc.Mapping[str, pathlib.Path],
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

    def __representation_out_file(
        self,
        representation: RepresentationRecord,
        cache_dir: pathlib.Path,
    ) -> pathlib.Path:
        return cache_dir / OUTFILE_NAME_PATTERN.format(
            repr_id=representation.representation_id,
            file_id=representation.association.association_id,
        )
