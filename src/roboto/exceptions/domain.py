# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
from typing import Any, Optional, Type

import pydantic
import pydantic_core

from ..collection_utils import get_by_path
from .http import HttpError

AUTHENTICATION_FAILURE_MESSAGE = (
    "Authentication to Roboto failed. This generally happens if the value in your "
    + "ROBOTO_BEARER_TOKEN environment variable or token in your ~/.roboto/config.json "
    + "file is expired or incorrectly formatted."
)


class RobotoDomainException(Exception):
    """
    Expected exceptions from the Roboto domain entity objects.
    """

    __headers: dict[str, str]
    _message: str
    _stack_trace: list[str]

    def __init__(
        self,
        message: str,
        stack_trace: list[str] = [],
        headers: dict[str, str] = {},
        *args,
        **kwargs,
    ):
        super().__init__(message, *args, **kwargs)
        self._message = message
        self._stack_trace = stack_trace
        self.__headers = headers

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Type[Any], handler: pydantic.GetCoreSchemaHandler
    ) -> pydantic_core.core_schema.CoreSchema:
        assert source is RobotoDomainException
        return pydantic_core.core_schema.no_info_after_validator_function(
            cls.from_json_string,
            pydantic_core.core_schema.str_schema(),
            serialization=pydantic_core.core_schema.plain_serializer_function_ser_schema(
                cls.to_dict,
                info_arg=False,
                return_schema=pydantic_core.core_schema.str_schema(),
            ),
        )

    @staticmethod
    def from_json(
        contents: dict[str, Any], headers: dict[str, str] = {}
    ) -> "RobotoDomainException":
        error_code = get_by_path(contents, ["error", "error_code"])
        inner_message = get_by_path(contents, ["error", "message"])
        kwargs: dict[str, Any] = {}
        error = get_by_path(contents, ["error"])
        if error is not None:
            kwargs.update(error)
            kwargs.pop("error_code")
            kwargs.pop("message")

        if error_code is None or inner_message is None:
            raise ValueError("Need 'error_code' and 'message' available.")

        for subclass in RobotoDomainException.__subclasses__():
            if subclass.__name__ == error_code:
                return subclass(message=inner_message, headers=headers, **kwargs)

        raise ValueError("Unrecognized error code 'error_code'")

    @staticmethod
    def from_json_string(contents: str) -> "RobotoDomainException":
        return RobotoDomainException.from_json(json.loads(contents))

    @staticmethod
    def from_client_error(error: HttpError) -> "RobotoDomainException":
        message: Optional[str]

        if type(error.msg) is dict:
            # See if it's a first class RobotoException
            try:
                return RobotoDomainException.from_json(error.msg, headers=error.headers)
            except ValueError:
                pass

            # Handle JSON from non-roboto calls
            message = error.msg.get("message", json.dumps(error.msg))
        elif type(error.msg) is str:
            message = error.msg
        else:
            message = None

        if error.status is None:
            raise RobotoDomainException(error.msg, headers=error.headers)
        if error.status == 400:
            if (
                message is not None
                and "did not provide a org for single-org operation" in message
            ):
                return RobotoNoOrgProvidedException(error.msg, headers=error.headers)
            else:
                return RobotoInvalidRequestException(error.msg, headers=error.headers)
        if error.status in (401, 403):
            if (
                message is not None
                and "User is not authorized to access this resource with an explicit deny"
                in message
            ):
                return RobotoAuthenticationFailureException(
                    AUTHENTICATION_FAILURE_MESSAGE, headers=error.headers
                )
            else:
                return RobotoUnauthorizedException(error.msg, headers=error.headers)
        if error.status == 404:
            return RobotoNotFoundException(error.msg, headers=error.headers)
        if 500 <= error.status < 600:
            return RobotoServiceException(error.msg, headers=error.headers)
        raise error

    @property
    def headers(self) -> dict[str, str]:
        return self.__headers

    @property
    def http_status_code(self) -> int:
        return 500

    @property
    def error_code(self) -> str:
        return self.__class__.__name__

    @property
    def message(self) -> str:
        return self._message

    @property
    def stack_trace(self) -> list[str]:
        return self._stack_trace

    @stack_trace.setter
    def stack_trace(self, stack_trace: list[str]):
        self._stack_trace = stack_trace

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"error_code": self.error_code, "message": self.message}
        if len(self._stack_trace) > 0:
            error["stack_trace"] = self._stack_trace
        return {"error": error}

    def serialize(self) -> str:
        return json.dumps(self.to_dict())


class RobotoUnauthorizedException(RobotoDomainException):
    """
    Thrown when a user is attempting to access a resource that they do not have permission to access
    """

    @property
    def http_status_code(self) -> int:
        return 401


class RobotoAuthenticationFailureException(RobotoDomainException):
    """
    Thrown when authentication fails
    """

    @property
    def http_status_code(self) -> int:
        return 401


class RobotoNotFoundException(RobotoDomainException):
    """
    Throw when a requested resource does not exist
    """

    @property
    def http_status_code(self) -> int:
        return 404


class RobotoNotReadyException(RobotoDomainException):
    """
    Throw when a requested resource is resolvable by ID/context but is not fully initialized or ready to be served.
    """

    @property
    def http_status_code(self) -> int:
        return 404


class RobotoIllegalArgumentException(RobotoDomainException):
    """
    Thrown when request parameters are in some way invalid
    """

    @property
    def http_status_code(self) -> int:
        return 400


class RobotoInvalidRequestException(RobotoDomainException):
    """
    Thrown when request parameters are in some way invalid
    """

    @property
    def http_status_code(self) -> int:
        return 400


class RobotoNotImplementedException(RobotoDomainException):
    """
    Thrown by shimmed out APIs which have not yet been implemented
    """

    @property
    def http_status_code(self) -> int:
        return 501


class RobotoDeprecatedException(RobotoDomainException):
    """
    Thrown when an old API endpoint is called, to tell the client to upgrade
    """

    @property
    def http_status_code(self) -> int:
        return 400


class RobotoInvalidStateTransitionException(RobotoDomainException):
    """
    Thrown when requesting update of state to an invalid state, or via an invalid transition path
    """

    @property
    def http_status_code(self) -> int:
        return 400


class RobotoNoOrgProvidedException(RobotoDomainException):
    """
    Thrown when no org is provided to an operation which requires an org.
    """

    @property
    def http_status_code(self) -> int:
        return 400


class RobotoConditionException(RobotoDomainException):
    """
    Thrown if there is a failed condition
    """

    @property
    def http_status_code(self) -> int:
        return 409


class RobotoConflictException(RobotoDomainException):
    """
    Thrown if there is a conflict between a resource you're creating and another existing resource
    """

    @property
    def http_status_code(self) -> int:
        return 409


class RobotoServiceException(RobotoDomainException):
    """
    Thrown when Roboto Service failed in an unexpected way
    """


class RobotoUnknownOperationException(RobotoDomainException):
    """
    Thrown if a user is attempting to perform an action unrecognized by the Roboto platform.
    """

    @property
    def http_status_code(self) -> int:
        return 404


class RobotoExpiredException(RobotoDomainException):
    """
    Thrown if a resource is missing or expired.
    """

    @property
    def http_status_code(self) -> int:
        return 410


class RobotoLimitExceededException(RobotoDomainException):
    """
    Thrown if an operation would exceed a user or org level limit.
    """

    __resource_name: str
    __current_quantity: int
    __limit_quantity: int

    def __init__(
        self,
        message: str,
        stack_trace: list[str] = [],
        *args,
        resource_name: str = "Unknown",
        current_quantity: int = 0,
        limit_quantity: int = 0,
        **kwargs,
    ):
        super().__init__(message, stack_trace, *args, **kwargs)
        self.__resource_name = resource_name
        self.__current_quantity = current_quantity
        self.__limit_quantity = limit_quantity

    @property
    def http_status_code(self) -> int:
        return 403

    @property
    def resource_name(self) -> str:
        return self.__resource_name

    @property
    def limit_quantity(self) -> int:
        return self.__limit_quantity

    @property
    def current_quantity(self) -> int:
        return self.__current_quantity

    def to_dict(self) -> dict[str, Any]:
        as_dict = super().to_dict()
        as_dict["error"]["resource_name"] = self.resource_name
        as_dict["error"]["current_quantity"] = self.current_quantity
        as_dict["error"]["limit_quantity"] = self.limit_quantity
        return as_dict


class RobotoInternalException(RobotoDomainException):
    """
    Thrown when Roboto throws an unexpected internal error, expected to be systemic.
    """

    @property
    def http_status_code(self) -> int:
        return 500


class RobotoServiceUnavailableException(RobotoDomainException):
    """
    Thrown when a service is unavailable, such as when it's under heavy load and can't accept new requests.
    This is expected to be transient and ought to be retried.
    """

    @property
    def http_status_code(self) -> int:
        return 503


class RobotoServiceTimeoutException(RobotoDomainException):
    """
    Thrown when the service times out while processing a request. This is exepcted to be transient and ought to be
    retried.
    """

    @property
    def http_status_code(self) -> int:
        return 504


class RobotoHttpExceptionParse(object):
    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        if issubclass(type(exception), HttpError):
            raise RobotoDomainException.from_client_error(error=exception) from None
