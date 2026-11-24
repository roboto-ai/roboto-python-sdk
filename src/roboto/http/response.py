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
"""Type of the values a ``BatchResponse``, ``BatchResponseElement``, ``PaginatedList`` or ``StreamedList`` holds."""

MappedModel = typing.TypeVar("MappedModel")
"""Type of the results a ``BatchResponse`` that ``BatchResponse.map_data`` returns holds."""

PydanticModel = typing.TypeVar("PydanticModel", bound=pydantic.BaseModel)
"""Type of the pydantic model an ``HttpResponse`` method parses the body as."""

DEFAULT_RESPONSE_JSONPATH = ("data",)
"""Path to the result within a Roboto response body: its top-level ``data`` field."""


class BatchResponseElement(pydantic.BaseModel, typing.Generic[Model]):
    """Outcome of one element of a batch request: its result if Roboto applied it, or its exception if refused.

    An element never holds both. One that holds neither was applied with no content to return, as a single request
    answered with HTTP 204 would be.
    """

    # Model can be a class that is not a pydantic model, such as Session (see BatchResponse.map_data). Pydantic cannot
    # build a schema for such a class, so without this setting it rejects BatchResponseElement[Session] itself, before
    # any response is parsed.
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    data: typing.Optional[Model] = None
    """Result of the element, or ``None`` if Roboto refused it or applied it with no content to return."""

    error: typing.Optional[RobotoDomainException] = None
    """Exception Roboto refused the element with, or ``None`` if Roboto applied it."""

    @pydantic.field_validator("error", mode="plain")
    def validate_error(cls, value: typing.Any) -> typing.Optional[RobotoDomainException]:
        """Build the exception an element was refused with, from whichever form the refusal arrived in.

        Pydantic calls this whenever an element is built or parsed. It accepts three forms:

        - An exception object, as an element copied from another batch carries.
        - The envelope :py:meth:`~roboto.exceptions.RobotoDomainException.to_dict` produces.
        - That envelope as JSON text, the form :py:class:`~roboto.exceptions.RobotoDomainException` declares to
          pydantic.

        Only ``None`` yields ``None``. Any other value is a refusal, whatever its shape: an envelope whose error code
        names no exception class in this SDK version, one missing its code or message, JSON that is not an envelope,
        and text that is not JSON all become a :py:class:`~roboto.exceptions.RobotoUnrecognizedErrorException`. It
        carries whatever code and message could be read, and the value's own text as its message when no message
        could be. A refused element therefore always appears in ``BatchResponse.failed``, so a caller that checks
        ``failed`` cannot mistake a malformed refusal for success.

        ``plain`` mode replaces the validation the ``error`` annotation would apply, which reads JSON text and would
        reject the exception object this returns.
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

        # from_json raises ValueError when no class in this SDK version matches the code or the envelope lacks its code
        # or message, and TypeError when the matched class's constructor rejects an envelope field. Every exception is
        # suppressed: one escaping a validator fails the parse of the whole batch, hiding Roboto's refusal of this one
        # element behind a pydantic error.
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
        """Serialize ``error`` as the envelope :py:meth:`~roboto.exceptions.RobotoDomainException.to_dict` produces.

        Pydantic calls this whenever an element is dumped, and ``validate_error`` reads the envelope back.
        """
        return None if value is None else value.to_dict()


class BatchResponse(pydantic.BaseModel, typing.Generic[Model]):
    """Response to a batch request: the outcome of each request element, in the order the request sent them.

    Roboto applies or refuses each element on its own, so a batch can come back partly applied. ``succeeded`` and
    ``failed`` split the outcomes for a caller that does not need to know which request element produced which;
    ``responses`` traces each outcome back to the request element at the same position.
    """

    responses: list[BatchResponseElement[Model]]
    """Outcome of each request element, at the same position as that element in the request."""

    @property
    def failed(self) -> list[RobotoDomainException]:
        """Exception Roboto refused each refused element with, in request order."""
        return [element.error for element in self.responses if element.error is not None]

    @property
    def succeeded(self) -> list[Model]:
        """Result of each applied element, in request order.

        Elements applied with no content to return appear in neither ``succeeded`` nor ``failed``.
        """
        return [element.data for element in self.responses if element.data is not None]

    def map_data(self, transform: collections.abc.Callable[[Model], MappedModel]) -> "BatchResponse[MappedModel]":
        """Return a batch whose results are this batch's results passed through ``transform``.

        ``Device.create_sessions`` turns each ``SessionRecord`` in Roboto's response into a ``Session`` through it, so
        most code never calls it. ``transform`` runs only on elements that hold a result; a refused element keeps its
        exception, and every element keeps its position.

        Args:
            transform: Function that builds the new result from an element's result.

        Returns:
            A new batch with one element per element of this one, in the same order. This batch is unchanged.
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
        """Return the result of the only element of a one-element batch.

        ``Device.create_session`` returns the result of its one-element batch through it, so most code never calls it.
        A refusal raises its exception instead of coming back inside a batch.

        Raises:
            RobotoDomainException: Roboto refused the element. The exception raised is the one Roboto reported.
            RobotoInternalException: The batch does not hold exactly one element, or its element holds neither a
                result nor an exception.
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
    """One page of a listing: the items on it, and a token that fetches the next page if there is one."""

    items: list[Model]
    """Items on this page."""

    next_token: typing.Optional[str] = None
    """Token that fetches the next page, or ``None`` if this is the last page. Pass it back unchanged."""

    total_count: typing.Optional[int] = None
    """Number of items across every page, or ``None`` if the listing does not report it."""


class StreamedList(pydantic.BaseModel, typing.Generic[Model]):
    """One read from a stream that may still be growing, such as the logs of an invocation that is running.

    A ``PaginatedList`` pages through a fixed set of items. A stream can gain items between reads
    and may never end, so a read that finds nothing more does not mean the stream is complete.
    """

    items: list[Model]
    """Items read from the stream."""

    last_read: typing.Optional[str]
    """Token that marks the position after the last item read, to pass back to read the items that follow it.

    ``None`` if Roboto returned no position to resume from.
    """

    has_next: bool
    """Whether more items are known to be available now, readable from ``last_read``.

    ``False`` does not mean the stream has ended: more items may be written later.
    """


class PaginationTokenEncoding(enum.Enum):
    """Encoding of the data a ``PaginationToken`` carries.

    Roboto uses it when it builds and parses page tokens.
    """

    Json = "json"
    """Data serialized as JSON."""

    Raw = "raw"
    """Data stored as a string, unchanged."""


class PaginationTokenScheme(enum.Enum):
    """Version of the ``PaginationToken`` format.

    Roboto uses it when it builds and parses page tokens.
    """

    V1 = "v1"


class InvalidPaginationTokenError(ValueError):
    """The pagination token does not parse.

    ``PaginationToken.from_token`` raises it. Pagination tokens are opaque to callers, so one that does not decode or
    names an unsupported scheme, such as a fabricated or truncated token, is an error in the caller's input rather than
    a failure in Roboto. Subclasses ``ValueError``, so code that catches ``ValueError`` around ``from_token`` catches it
    too.
    """


class PaginationToken:
    """Pagination token whose contents callers treat as opaque, with a version that lets its format change.

    Roboto uses it to build and parse the page tokens some of its listings return; callers pass those tokens back
    unchanged and have no reason to build one. ``to_token`` writes the scheme, the encoding and the data as
    ``<scheme>:<encoding>:<data>``, in URL-safe Base64 without ``=`` padding.

    Args:
        scheme: Version of the token format.
        encoding: How ``data`` is written into the token.
        data: Data the token carries: a string for ``PaginationTokenEncoding.Raw``, or any JSON-serializable value
            for ``Json``.
    """

    __scheme: PaginationTokenScheme
    __encoding: PaginationTokenEncoding
    __data: typing.Any

    @staticmethod
    def empty() -> "PaginationToken":
        """Return a token that carries no data."""
        return PaginationToken(PaginationTokenScheme.V1, PaginationTokenEncoding.Raw, None)

    @staticmethod
    def encode(data: str) -> str:
        """Return ``data`` in URL-safe Base64, with the trailing ``=`` padding removed."""
        return base64.urlsafe_b64encode(data.encode("utf-8")).decode("utf-8").rstrip("=")

    @staticmethod
    def decode(data: str) -> str:
        """Return the text that URL-safe Base64 ``data`` encodes, restoring any trailing ``=`` padding it lacks."""
        while len(data) % 4 != 0:
            data += "="
        return base64.urlsafe_b64decode(data).decode("utf-8")

    @classmethod
    def from_token(cls, token: typing.Optional[str]) -> "PaginationToken":
        """Parse a token string that ``to_token`` produced.

        Args:
            token: Token string to parse. ``None`` returns a token that carries no data.

        Raises:
            InvalidPaginationTokenError: ``token`` does not decode, does not name the ``v1`` scheme and a known
                encoding, or carries JSON data that does not parse.
        """
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
        # Every failure above, the scheme check's own InvalidPaginationTokenError included, is re-raised as one
        # InvalidPaginationTokenError without its cause; the warning logs the cause instead.
        except Exception as e:
            logger.warning(f"Invalid pagination token {token}", exc_info=e)
            raise InvalidPaginationTokenError("Invalid pagination token format") from None

    @classmethod
    def json_token(cls, data: typing.Any) -> "PaginationToken":
        """Build a token that carries ``data`` serialized as JSON.

        Args:
            data: JSON-serializable data to carry.
        """
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
        """Return the length of the token string, or 0 if the token carries no data, so such a token is falsy."""
        return len(str(self)) if self.__data else 0

    def __str__(self):
        return self.to_token()

    @property
    def data(self) -> typing.Any:
        """Data the token carries, already deserialized when the encoding is ``Json``."""
        return self.__data

    def to_token(self) -> str:
        """Render the token as the string ``from_token`` parses."""
        data = json.dumps(self.__data) if self.__encoding == PaginationTokenEncoding.Json else self.__data
        return PaginationToken.encode(f"{self.__scheme.value}:{self.__encoding.value}:{data}")


class HttpResponse:
    """Response to an HTTP request, with methods that parse its body.

    Returned by the request methods of :py:class:`~roboto.http.RobotoClient` and :py:class:`~roboto.http.HttpClient`.
    Each ``to_*`` method reads the body and closes the response, so call at most one of them per response. The
    methods that build records raise ``pydantic.ValidationError`` when the body does not match the record type.

    Args:
        response: Response ``urllib`` returned, with its body not yet read.
    """

    __response: urllib.response.addinfourl

    def __init__(self, response: urllib.response.addinfourl) -> None:
        super().__init__()
        self.__response = response

    @property
    def readable_response(self) -> urllib.response.addinfourl:
        """Response ``urllib`` returned, for reading the body directly."""
        return self.__response

    @property
    def status(self) -> http.HTTPStatus:
        """HTTP status of the response. Reading it raises ``RuntimeError`` if the response has no status code."""
        status_code = self.__response.status
        if status_code is None:
            raise RuntimeError("Response has no status code")
        return http.HTTPStatus(int(status_code))

    @property
    def headers(self) -> typing.Optional[dict[str, str]]:
        """Headers of the response, keyed by name. Of several headers with one name, the last is kept."""
        return dict(self.__response.headers.items())

    def to_paginated_list(self, record_type: typing.Type[PydanticModel]) -> PaginatedList[PydanticModel]:
        """Parse the page in the body's ``data`` field, validating each of its items as ``record_type``.

        The page's ``total_count`` is left ``None``, even when the body reports one.

        Args:
            record_type: Pydantic model to validate each item as.
        """
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
        """Parse the value at ``json_path`` in the body as one ``record_type``.

        Args:
            record_type: Pydantic model to validate the value as.
            json_path: Keys leading from the top of the body to the value, outermost first. Defaults to the body's
                ``data`` field. ``None`` parses the whole body.
        """
        return record_type.model_validate(self.to_dict(json_path=json_path))

    def to_record_list(
        self,
        record_type: typing.Type[PydanticModel],
        json_path: typing.Optional[collections.abc.Sequence[str]] = DEFAULT_RESPONSE_JSONPATH,
    ) -> list[PydanticModel]:
        """Parse the list at ``json_path`` in the body, validating each of its items as ``record_type``.

        Args:
            record_type: Pydantic model to validate each item as.
            json_path: Keys leading from the top of the body to the list, outermost first. Defaults to the body's
                ``data`` field. ``None`` parses the whole body.
        """
        return [record_type.model_validate(item) for item in self.to_dict(json_path=json_path)]

    def to_string_list(self) -> list[str]:
        """Return the items of the list in the body's ``data`` field, each converted to a string."""
        return [str(item) for item in self.to_dict(json_path=["data"])]

    def to_dict(self, json_path: typing.Optional[collections.abc.Sequence[str]] = None) -> typing.Any:
        """Parse the body as JSON and return it, or the value at ``json_path`` in it.

        The value can be any JSON value, not only an object.

        Args:
            json_path: Keys leading from the top of the body to the value, outermost first. ``None`` returns the
                whole body.

        Returns:
            The value at ``json_path``, or ``None`` if the path does not lead to a value.
        """
        with self.__response:
            unmarshalled = json.loads(self.__response.read().decode("utf-8"))
            if json_path is None:
                return unmarshalled

            return get_by_path(unmarshalled, json_path)

    def to_string(self):
        """Return the body decoded as UTF-8 text."""
        with self.__response:
            return self.__response.read().decode("utf-8")

    def to_int(self) -> int:
        """Return the body parsed as an integer.

        Raises:
            ValueError: The body is not an integer.
        """
        return int(self.to_string())
