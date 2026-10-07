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
    RobotoInternalException,
    RobotoUnrecognizedErrorException,
)

from ..collection_utils import get_by_path
from ..logging import default_logger

logger = default_logger()

Model = typing.TypeVar("Model")
MappedModel = typing.TypeVar("MappedModel")
PydanticModel = typing.TypeVar("PydanticModel", bound=pydantic.BaseModel)

DEFAULT_RESPONSE_JSONPATH = ("data",)


class BatchResponseElement(pydantic.BaseModel, typing.Generic[Model]):
    """
    One element of a response to a batch request, holding ``data`` when the operation succeeded and ``error`` when
    it failed, never both. An element holding neither reports an operation that returns no content, the batch
    equivalent of a 204 answer to a singular call.
    """

    # ``Model`` is parametrized over domain classes such as Session (see :py:meth:`BatchResponse.map_data`), and those
    # are plain classes rather than pydantic models. Pydantic cannot derive a schema for one, so without this it
    # refuses the parametrization itself, before any response is parsed.
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    data: typing.Optional[Model] = None
    error: typing.Optional[RobotoDomainException] = None

    @pydantic.field_validator("error", mode="plain")
    def validate_error(cls, value: typing.Any) -> typing.Optional[RobotoDomainException]:
        """Build the exception an element was refused with, in whichever form the failure arrived.

        Three forms reach this: an exception object, which is what an element copied from another batch
        carries; the envelope :py:meth:`RobotoDomainException.to_dict` produces; and that envelope as JSON
        text, which is what :py:class:`~roboto.exceptions.RobotoDomainException` declares to pydantic. Only a
        literal ``None`` yields ``None``, which is how an element the platform applied or answered with no
        content arrives.

        Any other value is a refusal, whatever shape it has. An envelope naming an exception class this
        release does not define, one missing its code or message, JSON that is not an envelope, and text
        that is not JSON all read as a :py:class:`~roboto.exceptions.RobotoUnrecognizedErrorException`
        carrying whatever code and message could be recovered, with the value's own text as the message when
        no message could be. That way a refused element is always in :py:attr:`BatchResponse.failed`, so a
        caller checking ``failed`` before treating a batch as done cannot mistake a garbled refusal for
        success.

        ``plain`` mode replaces the validation the ``error`` annotation would otherwise apply. That
        annotation reads JSON text, so it would reject the exception object returned here.
        """
        if value is None or isinstance(value, RobotoDomainException):
            return value

        if isinstance(value, (str, bytes, bytearray)):
            raw_text = value if isinstance(value, str) else value.decode(errors="replace")
            try:
                envelope = json.loads(value)
            except ValueError:
                return RobotoUnrecognizedErrorException(message=raw_text)
        else:
            raw_text = repr(value)
            envelope = value

        if not isinstance(envelope, dict):
            return RobotoUnrecognizedErrorException(message=raw_text)

        # from_json raises ValueError on a code no class in this release matches or an envelope missing its
        # code or message, and TypeError on an envelope field the matched class's constructor rejects. Every
        # exception is swallowed: letting one escape a validator fails the parse of the whole batch, hiding
        # the platform's refusal of this one element behind a pydantic error.
        try:
            return RobotoDomainException.from_json(envelope)
        except Exception:
            pass

        error = envelope.get("error")
        if not isinstance(error, dict):
            error = {}

        error_code, message = error.get("error_code"), error.get("message")
        return RobotoUnrecognizedErrorException(
            message=message if isinstance(message, str) else raw_text,
            error_code=error_code if isinstance(error_code, str) else None,
        )

    @pydantic.field_serializer("error")
    def serialize_error(
        self,
        value: typing.Optional[RobotoDomainException],
        info: pydantic.SerializationInfo,
    ) -> typing.Optional[dict[str, typing.Any]]:
        return None if value is None else value.to_dict()


class BatchResponse(pydantic.BaseModel, typing.Generic[Model]):
    """
    The response to a batch request, holding one element per request element, in the order the request sent them.

    Every element of a batch is applied or refused on its own, so a batch can come back partly applied.
    :py:attr:`succeeded` and :py:attr:`failed` split the outcomes for a caller that does not care which request
    element produced which; read ``responses`` to trace an outcome back to the request element at its position.
    """

    responses: list[BatchResponseElement[Model]]

    @property
    def failed(self) -> list[RobotoDomainException]:
        """The exception the platform reported for each element it refused, in request order."""
        return [element.error for element in self.responses if element.error is not None]

    @property
    def succeeded(self) -> list[Model]:
        """The result the platform returned for each element it applied, in request order."""
        return [element.data for element in self.responses if element.data is not None]

    def map_data(self, transform: collections.abc.Callable[[Model], MappedModel]) -> "BatchResponse[MappedModel]":
        """Convert what each applied element carries, leaving positions and failures untouched.

        A batch call parses the platform's answer into records and uses this to hand the caller domain objects
        instead: a ``SessionRecord`` becomes a ``Session``. ``transform`` runs only on elements carrying data; a
        refused element keeps its exception, and every element keeps its position.

        Args:
            transform: Builds the domain object an applied element's record stands for.

        Returns:
            A batch holding one element per element of this one, in the same order.
        """
        return BatchResponse[MappedModel](
            responses=[
                BatchResponseElement[MappedModel](
                    data=None if element.data is None else transform(element.data),
                    error=element.error,
                )
                for element in self.responses
            ]
        )

    def single(self) -> Model:
        """The result carried by the only element of a one-element batch.

        A singular call such as :py:meth:`~roboto.domain.devices.Device.create_session` sends its one element
        through the plural counterpart and unwraps the answer with this, so its caller gets a raised exception
        rather than a batch to inspect.

        Raises:
            RobotoDomainException: Whatever the platform refused the element with.
            RobotoInternalException: The batch does not hold exactly one element, or holds one carrying
                neither a result nor an error.
        """
        if len(self.responses) != 1:
            raise RobotoInternalException(f"Expected one response to a single-element batch, got {len(self.responses)}")
        element = self.responses[0]
        if element.error is not None:
            raise element.error
        if element.data is None:
            raise RobotoInternalException("The platform reported neither a result nor an error for this element")
        return element.data


class PaginatedList(pydantic.BaseModel, typing.Generic[Model]):
    """
    A list of records pulled from a paginated result set.
    It may be a subset of that result set,
    in which case ``next_token`` will be set and can be used to fetch the next page.
    """

    items: list[Model]
    """Roboto entities in this page of results."""

    next_token: typing.Optional[str] = None
    """Opaque token to fetch the next page of results.

    If ``None``, then this is the last page of results.
    """

    total_count: typing.Optional[int] = None
    """Total result set size, if available."""


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
    """Pagination token encoding enum"""

    Json = "json"
    Raw = "raw"


class PaginationTokenScheme(enum.Enum):
    """Pagination token scheme enum"""

    V1 = "v1"


class InvalidPaginationTokenError(ValueError):
    """Raised when a pagination token cannot be parsed.

    A pagination token is opaque to clients, so one that fails to decode or carries
    an unsupported scheme reflects bad caller input — a fabricated, truncated, or
    stale token — rather than a server fault. Subclasses ``ValueError`` so existing
    callers that catch ``ValueError`` around :meth:`PaginationToken.from_token` keep
    working unchanged, while callers that want to distinguish this recoverable
    input error (e.g. to surface an actionable message instead of a generic 500 or
    runtime exception) can catch it specifically.
    """


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
        return PaginationToken(PaginationTokenScheme.V1, PaginationTokenEncoding.Raw, None)

    @staticmethod
    def encode(data: str) -> str:
        """Base64 encode the data and strip all trailing padding ("=")."""
        return base64.urlsafe_b64encode(data.encode("utf-8")).decode("utf-8").rstrip("=")

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
                logger.warning("Invalid pagination token scheme %s", decoded)
                raise InvalidPaginationTokenError("Invalid pagination token scheme")
            scheme, encoding, data = decoded.split(":", maxsplit=2)
            pagination_token_scheme = PaginationTokenScheme(scheme)
            pagination_token_encoding = PaginationTokenEncoding(encoding)
            return cls(
                pagination_token_scheme,
                pagination_token_encoding,
                (json.loads(data) if pagination_token_encoding == PaginationTokenEncoding.Json else data),
            )
        except Exception as e:
            logger.warning(f"Invalid pagination token {token}", exc_info=e)
            raise InvalidPaginationTokenError("Invalid pagination token format") from None

    @classmethod
    def json_token(cls, data: typing.Any) -> "PaginationToken":
        return cls(
            scheme=PaginationTokenScheme.V1,
            encoding=PaginationTokenEncoding.Json,
            data=data,
        )

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
        data = json.dumps(self.__data) if self.__encoding == PaginationTokenEncoding.Json else self.__data
        return PaginationToken.encode(f"{self.__scheme.value}:{self.__encoding.value}:{data}")


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

    def to_paginated_list(self, record_type: typing.Type[PydanticModel]) -> PaginatedList[PydanticModel]:
        unmarshalled = self.to_dict(json_path=["data"])
        return PaginatedList(
            items=[record_type.model_validate(item) for item in unmarshalled["items"]],
            next_token=unmarshalled["next_token"],
        )

    def to_record(
        self,
        record_type: typing.Type[PydanticModel],
        json_path: typing.Optional[collections.abc.Sequence[str]] = DEFAULT_RESPONSE_JSONPATH,
    ) -> PydanticModel:
        return record_type.model_validate(self.to_dict(json_path=json_path))

    def to_record_list(
        self,
        record_type: typing.Type[PydanticModel],
        json_path: typing.Optional[collections.abc.Sequence[str]] = DEFAULT_RESPONSE_JSONPATH,
    ) -> list[PydanticModel]:
        return [record_type.model_validate(item) for item in self.to_dict(json_path=json_path)]

    def to_string_list(self) -> list[str]:
        return [str(item) for item in self.to_dict(json_path=["data"])]

    def to_dict(self, json_path: typing.Optional[collections.abc.Sequence[str]] = None) -> typing.Any:
        with self.__response:
            unmarshalled = json.loads(self.__response.read().decode("utf-8"))
            if json_path is None:
                return unmarshalled

            return get_by_path(unmarshalled, json_path)

    def to_string(self):
        with self.__response:
            return self.__response.read().decode("utf-8")

    def to_int(self) -> int:
        return int(self.to_string())
