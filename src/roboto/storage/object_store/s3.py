# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections
import multiprocessing
import pathlib
import re
import threading
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
    Credentials,
    FutureLike,
    ObjectStore,
    OnProgress,
)
from .registry import StoreRegistry


# Adapted from boto3.s3.transfer.ProgressCallbackInvoker.
class ProgressCallbackInvoker(boto3.s3.transfer.BaseSubscriber):
    """Transfer subscriber that passes each progress update's byte count to a callback.

    ``S3Store.put`` and ``S3Store.get`` report progress through it when given an ``on_progress`` callback, so most
    code never builds one.

    Args:
        callback: Function called with the number of bytes transferred since its previous call.
    """

    def __init__(self, callback):
        self._callback = callback

    def on_progress(self, bytes_transferred, **kwargs):
        self._callback(bytes_transferred)


@StoreRegistry.register("s3")
class S3Store(ObjectStore):
    """Object store that copies files to and from Amazon S3, selected for ``s3://`` URIs.

    :py:meth:`~roboto.storage.object_store.StoreRegistry.get_store_for_uri` builds one through ``create``, so most code
    never builds one. Use it as a context manager: leaving the ``with`` block waits for every upload and download
    started in it to finish.

    Args:
        s3_client: boto3 S3 client to transfer with.
        transfer_config: Thread and part-size settings for transfers. ``None`` uses boto3's defaults.
    """

    @classmethod
    def create(cls, credential_provider: CredentialProvider, **kwargs) -> S3Store:
        """Build an S3 store that fetches new credentials from Roboto before the current ones expire.

        :py:meth:`~roboto.storage.object_store.StoreRegistry.get_store_for_uri` builds stores for ``s3://`` URIs
        through it, so most code never calls it. The store transfers on up to twice as many threads as the machine
        has CPUs, and at least 10. When the first credentials set ``send_requests_to``, the store sends each request
        to the URL of the credentials that signed it, as :py:attr:`~roboto.storage.RobotoCredentials.send_requests_to`
        describes, and a request signed with credentials older than the two most recent raises ``RuntimeError`` when
        it is sent.

        Args:
            credential_provider: Function that fetches temporary credentials from Roboto. Called once here, for the
                first credentials and their region, and again whenever the current credentials near their expiry.
            **kwargs: Ignored.
        """
        creds = credential_provider()

        # A request is sent to the URL of the credentials that signed it, not of the newest ones: other threads still
        # hold requests signed with the previous credentials when a refresh installs new ones.
        send_requests_to = _RecentSendRequestsTo()
        send_requests_to.remember(creds["access_key"], creds.get("send_requests_to"))

        def refresh() -> Credentials:
            refreshed = credential_provider()
            send_requests_to.remember(refreshed["access_key"], refreshed.get("send_requests_to"))
            return refreshed

        refreshable_creds = botocore.credentials.RefreshableCredentials.create_from_metadata(
            metadata=creds,
            refresh_using=refresh,
            method="roboto-api",
        )

        session = botocore.session.get_session()
        # botocore's public Session.set_credentials only accepts fixed credentials, which would never refresh.
        session._credentials = refreshable_creds
        session.set_config_variable("region", creds["region"])

        boto_session = boto3.Session(botocore_session=session)

        max_concurrency = max(10, multiprocessing.cpu_count() * 2)
        s3_client = boto_session.client(
            "s3",
            config=botocore.config.Config(
                tcp_keepalive=True,
                max_pool_connections=max_concurrency,
                request_checksum_calculation="when_supported",
                response_checksum_validation="when_supported",
            ),
        )

        if creds.get("send_requests_to"):
            _send_requests_to(s3_client, send_requests_to)

        transfer_config = boto3.s3.transfer.TransferConfig(use_threads=True, max_concurrency=max_concurrency)

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

    def put(
        self, source: pathlib.Path, destination_uri: str, on_progress: typing.Optional[OnProgress] = None
    ) -> FutureLike[None]:
        parsed_uri = urllib.parse.urlparse(destination_uri, allow_fragments=False)
        bucket = parsed_uri.netloc
        key = parsed_uri.path.lstrip("/")

        subscribers = []
        if on_progress is not None:
            subscribers.append(ProgressCallbackInvoker(on_progress))

        return self.__transfer_manager.upload(
            str(source),
            bucket,
            key,
            subscribers=subscribers,
        )

    def get(
        self, source_uri: str, destination: pathlib.Path, on_progress: typing.Optional[OnProgress] = None
    ) -> FutureLike[None]:
        destination.parent.mkdir(parents=True, exist_ok=True)

        parsed_uri = urllib.parse.urlparse(source_uri, allow_fragments=False)
        bucket = parsed_uri.netloc
        key = parsed_uri.path.lstrip("/")

        subscribers = []
        if on_progress is not None:
            subscribers.append(ProgressCallbackInvoker(on_progress))

        return self.__transfer_manager.download(
            bucket,
            key,
            str(destination),
            subscribers=subscribers,
        )


class _RecentSendRequestsTo:
    """URLs that receive the requests signed with the two most recent sets of credentials, by access key.

    Only the current and the previous set are kept: botocore refreshes credentials well before they expire, and
    requests signed with the previous set finish long before a third set is issued.
    """

    _REMEMBERED = 2

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._base_urls: collections.OrderedDict[str, typing.Optional[str]] = collections.OrderedDict()

    def remember(self, access_key: str, base_url: typing.Optional[str]) -> None:
        with self._lock:
            self._base_urls[access_key] = base_url
            self._base_urls.move_to_end(access_key)
            while len(self._base_urls) > self._REMEMBERED:
                self._base_urls.popitem(last=False)

    def base_url_for(self, access_key: str) -> typing.Optional[str]:
        """Return the URL that receives requests ``access_key`` signed, or ``None`` if they go to S3 directly.

        Raises:
            KeyError: ``access_key`` is not among the remembered credentials.
        """
        with self._lock:
            return self._base_urls[access_key]


_AUTHORIZATION_ACCESS_KEY = re.compile(r"\bCredential=([^/,\s]+)/")


def _signing_access_key(request: typing.Any) -> typing.Optional[str]:
    """Return the access key that signed ``request``, or ``None`` when the request names none."""
    authorization = request.headers.get("Authorization")
    if authorization:
        if isinstance(authorization, bytes):
            authorization = authorization.decode()
        match = _AUTHORIZATION_ACCESS_KEY.search(authorization)
        return match.group(1) if match else None

    credential = urllib.parse.parse_qs(urllib.parse.urlsplit(request.url).query).get("X-Amz-Credential")
    return credential[0].split("/", 1)[0] if credential else None


def _send_requests_to(s3_client: botocore.client.BaseClient, base_urls: _RecentSendRequestsTo) -> None:
    """Make ``s3_client`` send each request to the URL of the credentials that signed it, in place of S3.

    The request goes to that URL followed by the host and path it was signed for, with its query unchanged, as
    :py:attr:`~roboto.storage.RobotoCredentials.send_requests_to` describes. A request goes to S3 itself when its
    credentials name no URL. Each request is still signed for S3, so the server that receives it can send it on to S3.

    The URL is chosen by the access key in the request's signature, taken from its ``Authorization`` header or, for a
    presigned request, its ``X-Amz-Credential`` query parameter. A request signed before a refresh can be sent after
    it, and the URL carries a ticket that the server accepts only for requests signed with the access key of the same
    credentials.

    Raises:
        RuntimeError: When a request is sent, if it is unsigned or signed with an access key that is not among the
            remembered credentials. No URL is known to accept it, and S3 itself may be unreachable from where the
            credentials are used, so the request is refused rather than sent somewhere it would fail with a 404.
    """

    def replace_url(request: typing.Any, **kwargs: typing.Any) -> None:
        access_key = _signing_access_key(request)
        try:
            if access_key is None:
                raise KeyError(access_key)
            base = base_urls.base_url_for(access_key)
        except KeyError:
            raise RuntimeError(
                "Refusing to send a request signed with credentials that are no longer remembered: "
                "no URL is known to accept it."
            ) from None
        if not base:
            return
        signed_for = urllib.parse.urlsplit(request.url)
        query = f"?{signed_for.query}" if signed_for.query else ""
        request.url = f"{base.rstrip('/')}/{signed_for.netloc}{signed_for.path or '/'}{query}"

    # botocore emits before-send after it has signed the request, so the signature covers the S3 URL.
    s3_client.meta.events.register("before-send.s3", replace_url)
