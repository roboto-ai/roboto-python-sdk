# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import multiprocessing
import pathlib
import typing
import urllib.parse

import boto3
import boto3.s3.transfer
import botocore.client
import botocore.config
import botocore.credentials
import botocore.session

from .object_store import (
    CredentialProvider,
    FutureLike,
    ObjectStore,
)
from .registry import StoreRegistry


@StoreRegistry.register("s3")
class S3Store(ObjectStore):
    @classmethod
    def create(cls, credential_provider: CredentialProvider, **kwargs) -> S3Store:
        """
        Factory function to assemble an S3Store with refreshable credentials.
        """

        # 1. Fetch initial credentials to bootstrap
        creds = credential_provider()

        # 2. Build the RefreshableCredentials object
        refreshable_creds = botocore.credentials.RefreshableCredentials.create_from_metadata(
            metadata=creds,
            refresh_using=credential_provider,
            method="roboto-api",
        )

        # 3. Attach to a Botocore Session
        session = botocore.session.get_session()
        session._credentials = refreshable_creds
        session.set_config_variable("region", creds["region"])

        # 4. Create the high-level Boto3 Session
        boto_session = boto3.Session(botocore_session=session)

        # 5. Create the Client and TransferConfig
        s3_client = boto_session.client("s3", config=botocore.config.Config(tcp_keepalive=True))

        transfer_config = boto3.s3.transfer.TransferConfig(
            use_threads=True, max_concurrency=multiprocessing.cpu_count() * 2
        )

        # 6. Inject/instantiate
        return cls(s3_client, transfer_config=transfer_config)

    def __init__(
        self,
        s3_client: botocore.client.BaseClient,
        transfer_config: typing.Optional[boto3.s3.transfer.TransferConfig] = None,
    ):
        config = transfer_config or boto3.s3.transfer.TransferConfig()
        self.__transfer_manager = boto3.s3.transfer.create_transfer_manager(s3_client, config)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__transfer_manager.shutdown()

    def put(self, source: pathlib.Path, destination_uri: str) -> FutureLike[None]:
        parsed_uri = urllib.parse.urlparse(destination_uri)
        bucket = parsed_uri.netloc
        key = parsed_uri.path.lstrip("/")
        return self.__transfer_manager.upload(
            str(source),
            bucket,
            key,
        )
