# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import base64
import collections.abc
import enum
import http
import http.client
import json
import typing
import urllib.response

import pydantic

from roboto.exceptions import (
    RobotoDomainException,
)

from ..collection_utils import get_by_path
from ..logging import default_logger

logger = default_logger()

Model = typing.TypeVar("Model")
PydanticModel = typing.TypeVar("PydanticModel", bound=pydantic.BaseModel)


class BatchResponseElement(pydantic.BaseModel, typing.Generic[Model]):
    """
    One element of a response to a batch request. This should only ever have data set (in case of a successful
    operation) or error set (in case of a failed operation). For operations that do not return a response, an empty
    (data = None, error = None) Batch Response Element will be effectively equivalent to a single requests 204 No
    Content
    """

    data: typing.Optional[Model] = None
    error: typing.Optional[RobotoDomainException] = None

    @pydantic.field_validator("error", mode="before")
    def validate_error(cls, value: str) -> typing.Optional[RobotoDomainException]:
        try:
            return RobotoDomainException.from_json(json.loads(value))
        except Exception:
            return None

    @pydantic.field_serializer("error")
    def serialize_error(
        self,
        value: typing.Optional[RobotoDomainException],
        info: pydantic.SerializationInfo,
    ) -> typing.Optional[dict[str, typing.Any]]:
        return None if value is None else value.to_dict()


class BatchResponse(pydantic.BaseModel, typing.Generic[Model]):
    """
    The response to a batch request. The responses element contains one response (either success data or failure error)
    per request element, in the order in which the request was sent.
    """

    responses: list[BatchResponseElement[Model]]


class PaginatedList(pydantic.BaseModel, typing.Generic[Model]):
    """
    A list of records pulled from a paginated result set.
    It may be a subset of that result set,
    in which case `next_token` will be set and can be used to fetch the next page.
    """

    items: list[Model]
    # Opaque token that can be used to fetch the next page of results.
    next_token: typing.Optional[str] = None


class StreamedList(pydantic.BaseModel, typing.Generic[Model]):
    """
    A StreamedList differs from a PaginatedList in that it represents a stream of data that is
    in process of being written to. Unlike a result set, which is finite and complete,
    a stream may be infinite, and it is unknown when or if it will complete.
    """

    items: list[Model]
    # Opaque token that can be used to fetch the next page of results.
    last_read: typing.Optional[str]
    # If True, it is known that there are more items to be fetched;
    # use `last_read` as a pagination token to fetch those additional records.
    # If False, it is not known if there are more items to be fetched.
    has_next: bool


class PaginationTokenEncoding(enum.Enum):
    Json = "json"
    Raw = "raw"


class PaginationTokenScheme(enum.Enum):
    V1 = "v1"


class PaginationToken:
    """
    A pagination token that can be treated as a truly opaque token by clients,
    with support for evolving the token format over time.
    """

    __scheme: PaginationTokenScheme
    __encoding: PaginationTokenEncoding
    __data: typing.Any

    @staticmethod
    def empty() -> "PaginationToken":
        return PaginationToken(
            PaginationTokenScheme.V1, PaginationTokenEncoding.Raw, None
        )

    @staticmethod
    def encode(data: str) -> str:
        """Base64 encode the data and strip all trailing padding ("=")."""
        return (
            base64.urlsafe_b64encode(data.encode("utf-8")).decode("utf-8").rstrip("=")
        )

    @staticmethod
    def decode(data: str) -> str:
        """Base64 decode the data, adding back any trailing padding ("=") as necessary to make data properly Base64."""
        while len(data) % 4 != 0:
            data += "="
        return base64.urlsafe_b64decode(data).decode("utf-8")

    @classmethod
    def from_token(cls, token: typing.Optional[str]) -> "PaginationToken":
        if token is None:
            return PaginationToken.empty()
        try:
            decoded = PaginationToken.decode(token)
            if not decoded.startswith(PaginationTokenScheme.V1.value):
                logger.error("Invalid pagination token scheme %s", decoded)
                raise ValueError("Invalid pagination token scheme")
            scheme, encoding, data = decoded.split(":", maxsplit=2)
            pagination_token_scheme = PaginationTokenScheme(scheme)
            pagination_token_encoding = PaginationTokenEncoding(encoding)
            return cls(
                pagination_token_scheme,
                pagination_token_encoding,
                (
                    json.loads(data)
                    if pagination_token_encoding == PaginationTokenEncoding.Json
                    else data
                ),
            )
        except Exception as e:
            logger.error(f"Invalid pagination token {token}", exc_info=e)
            raise ValueError("Invalid pagination token format") from None

    def __init__(
        self,
        scheme: PaginationTokenScheme,
        encoding: PaginationTokenEncoding,
        data: typing.Any,
    ):
        self.__scheme = scheme
        self.__encoding = encoding
        self.__data = data

    def __len__(self):
        return len(str(self)) if self.__data else 0

    def __str__(self):
        return self.to_token()

    @property
    def data(self) -> typing.Any:
        return self.__data

    def to_token(self) -> str:
        data = (
            json.dumps(self.__data)
            if self.__encoding == PaginationTokenEncoding.Json
            else self.__data
        )
        return PaginationToken.encode(
            f"{self.__scheme.value}:{self.__encoding.value}:{data}"
        )


class HttpResponse:
    __response: urllib.response.addinfourl

    def __init__(self, response: urllib.response.addinfourl) -> None:
        super().__init__()
        self.__response = response

    @property
    def readable_response(self) -> urllib.response.addinfourl:
        return self.__response

    @property
    def status(self) -> http.HTTPStatus:
        status_code = self.__response.status
        if status_code is None:
            raise RuntimeError("Response has no status code")
        return http.HTTPStatus(int(status_code))

    @property
    def headers(self) -> typing.Optional[dict[str, str]]:
        return dict(self.__response.headers.items())

    def to_paginated_list(
        self, record_type: typing.Type[PydanticModel]
    ) -> PaginatedList[PydanticModel]:
        unmarshalled = self.to_dict(json_path=["data"])
        return PaginatedList(
            items=[record_type.model_validate(item) for item in unmarshalled["items"]],
            next_token=unmarshalled["next_token"],
        )

    def to_record(self, record_type: typing.Type[PydanticModel]) -> PydanticModel:
        return record_type.model_validate(self.to_dict(json_path=["data"]))

    def to_record_list(
        self, record_type: typing.Type[PydanticModel]
    ) -> collections.abc.Sequence[PydanticModel]:
        return [
            record_type.model_validate(item)
            for item in self.to_dict(json_path=["data"])
        ]

    def to_dict(self, json_path: typing.Optional[list[str]] = None) -> typing.Any:
        with self.__response:
            unmarsalled = json.loads(self.__response.read().decode("utf-8"))
            if json_path is None:
                return unmarsalled

            return get_by_path(unmarsalled, json_path)

    def to_string(self):
        with self.__response:
            return self.__response.read().decode("utf-8")
