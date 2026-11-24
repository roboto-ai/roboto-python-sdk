# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections
import collections.abc
import json
from typing import Any, Optional, Type

import pydantic
import pydantic_core

from ..collection_utils import get_by_path
from ..compat import StrEnum
from ..warnings import experimental
from .http import HttpError

AUTHENTICATION_FAILURE_MESSAGE = (
    "Authentication to Roboto failed. This generally happens if the value in your "
    + "ROBOTO_BEARER_TOKEN environment variable or token in your ~/.roboto/config.json "
    + "file is expired or incorrectly formatted."
)
"""Message of the authentication failure the SDK raises when Roboto rejects the caller's token.

Carried by ``RobotoAuthenticationFailureException``.
"""


class RobotoDomainException(Exception):
    """Base class of the exceptions the SDK raises when Roboto refuses a request or fails to complete it.

    Roboto reports an error as an envelope, ``{"error": {"error_code": ..., "message": ...}}``, whose ``error_code``
    is the name of a subclass, and the SDK raises that subclass. Some subclasses carry more fields in the envelope,
    such as the limit in ``RobotoLimitExceededException``. The SDK also raises some
    subclasses itself, for input it rejects before sending a request.
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
        if source is not RobotoDomainException:
            raise RuntimeError("Expected source to be RobotoDomainException")
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
    def from_json(contents: dict[str, Any], headers: dict[str, str] = {}) -> "RobotoDomainException":
        """Build the exception an error envelope describes.

        Args:
            contents: Error envelope, ``{"error": {"error_code": ..., "message": ...}}``. Every other field of
                ``error`` is passed to the subclass's constructor as a keyword argument.
            headers: HTTP headers of the response that carried the envelope.

        Returns:
            An instance of the subclass whose name is the envelope's ``error_code``.

        Raises:
            ValueError: The envelope lacks ``error_code`` or ``message``, or ``error_code`` names no subclass in this
                release of the SDK.
            TypeError: The envelope has a field the subclass's constructor does not accept.
        """
        error_code = get_by_path(contents, ["error", "error_code"])
        inner_message = get_by_path(contents, ["error", "message"])

        if error_code is None or inner_message is None:
            raise ValueError("Need 'error_code' and 'message' available.")

        # The check above guarantees both keys exist, so neither pop below raises KeyError.
        kwargs: dict[str, Any] = {}
        error = get_by_path(contents, ["error"])
        if error is not None:
            kwargs.update(error)
            kwargs.pop("error_code")
            kwargs.pop("message")

        # Walk the whole subclass tree, so a subclass of a subclass (RobotoLayoutConflictException under
        # RobotoConflictException) resolves too. Walking breadth-first makes the shallower class win if two
        # classes ever share a name.
        subclass_queue = collections.deque(RobotoDomainException.__subclasses__())
        while subclass_queue:
            subclass = subclass_queue.popleft()
            if subclass.__name__ == error_code:
                return subclass(message=inner_message, headers=headers, **kwargs)
            subclass_queue.extend(subclass.__subclasses__())

        raise ValueError(f"Unrecognized error code {error_code!r}")

    @staticmethod
    def from_json_string(contents: str) -> "RobotoDomainException":
        """Build the exception that an error envelope, as JSON text, describes.

        Parses ``contents`` and passes it, without headers, to ``from_json``, whose failures also apply.

        Args:
            contents: Error envelope as JSON text.

        Raises:
            ValueError: ``contents`` is not JSON.
        """
        return RobotoDomainException.from_json(json.loads(contents))

    @staticmethod
    def from_client_error(error: HttpError) -> "RobotoDomainException":
        """Convert an HTTP error response from Roboto into the matching exception.

        The request methods of :py:class:`~roboto.http.RobotoClient` convert every error response through it, so most
        code never calls it. When the response body is an error envelope that ``from_json`` recognizes, this returns
        the exception the envelope names. Otherwise it picks one by HTTP status:

        - 400: ``RobotoNoOrgProvidedException`` when the message says the request named no organization, otherwise
          ``RobotoInvalidRequestException``.
        - 401 or 403: ``RobotoAuthenticationFailureException`` when Roboto rejected the caller's token, otherwise
          ``RobotoUnauthorizedException``.
        - 404: ``RobotoDeviceNotFoundException`` or ``RobotoDatasetNotFoundException`` when the message names one,
          otherwise ``RobotoNotFoundException``.
        - 409: ``RobotoConflictException``.
        - 500 to 599: ``RobotoServiceException``.

        Args:
            error: HTTP error a request to Roboto raised.

        Raises:
            RobotoDomainException: The response's status code is not a standard HTTP status.
            HttpError: The response's status is none of those above. ``error`` itself is re-raised.
        """
        message: Optional[str]

        if type(error.msg) is dict:
            # from_json raises ValueError for a body that is not an error envelope, or that names an exception this
            # release lacks. Fall back to the HTTP status for those.
            try:
                return RobotoDomainException.from_json(error.msg, headers=error.headers)
            except ValueError:
                pass

            # JSON that is not an error envelope: use its "message" field, or else the whole body.
            message = error.msg.get("message", json.dumps(error.msg))
        elif type(error.msg) is str:
            message = error.msg
        else:
            message = None

        if error.status is None:
            raise RobotoDomainException(error.msg, headers=error.headers)
        if error.status == 400:
            if message is not None and "did not provide a org for single-org operation" in message:
                return RobotoNoOrgProvidedException(error.msg, headers=error.headers)
            else:
                return RobotoInvalidRequestException(error.msg, headers=error.headers)
        if error.status in (401, 403):
            if (
                message is not None
                and "User is not authorized to access this resource with an explicit deny" in message
            ):
                return RobotoAuthenticationFailureException(AUTHENTICATION_FAILURE_MESSAGE, headers=error.headers)
            else:
                return RobotoUnauthorizedException(error.msg, headers=error.headers)
        if error.status == 404:
            if message is not None and "RobotoDeviceNotFoundException" in message:
                return RobotoDeviceNotFoundException(error.msg, headers=error.headers)
            if message is not None and "RobotoDatasetNotFoundException" in message:
                return RobotoDatasetNotFoundException(error.msg, headers=error.headers)
            return RobotoNotFoundException(error.msg, headers=error.headers)
        if error.status == 409:
            return RobotoConflictException(error.msg, headers=error.headers)
        if 500 <= error.status < 600:
            return RobotoServiceException(error.msg, headers=error.headers)
        raise error

    @property
    def headers(self) -> dict[str, str]:
        """HTTP headers of the response that reported the error, or an empty dictionary when no response did."""
        return self.__headers

    @property
    def http_status_code(self) -> int:
        """HTTP status Roboto responds with when it reports this error."""
        return 500

    @property
    def error_code(self) -> str:
        """Code that identifies the error in its envelope: the name of this class."""
        return self.__class__.__name__

    @property
    def message(self) -> str:
        """Human-readable description of the error."""
        return self._message

    @property
    def stack_trace(self) -> list[str]:
        """Stack trace Roboto attached to the error, or an empty list when it attached none."""
        return self._stack_trace

    @stack_trace.setter
    def stack_trace(self, stack_trace: list[str]):
        self._stack_trace = stack_trace

    def to_dict(self) -> dict[str, Any]:
        """Return the error as an envelope, the form that ``from_json`` reads.

        The envelope holds ``error_code`` and ``message``, ``stack_trace`` when it is not empty, and any fields the
        subclass adds.
        """
        error: dict[str, Any] = {"error_code": self.error_code, "message": self.message}
        if len(self._stack_trace) > 0:
            error["stack_trace"] = self._stack_trace
        return {"error": error}

    def serialize(self) -> str:
        """Render the envelope from ``to_dict`` as JSON text."""
        return json.dumps(self.to_dict())


class RobotoUnauthorizedException(RobotoDomainException):
    """The caller lacks permission for the request."""

    @property
    def http_status_code(self) -> int:
        return 401


class RobotoOrgCreationRefusedException(RobotoUnauthorizedException):
    """The sign-up policy of the Roboto deployment does not let the caller create an organization now.

    :py:meth:`~roboto.domain.orgs.Org.create` raises it. A caller who owns as many organizations as they may gets
    ``RobotoLimitExceededException`` instead.
    """

    def __init__(
        self,
        message: str,
        next_step: str,
        reason: Optional[str] = None,
        stack_trace: list[str] = [],
        headers: dict[str, str] = {},
        *args,
        **kwargs,
    ):
        super().__init__(message, stack_trace, headers, *args, **kwargs)
        self.next_step = next_step
        """What the caller can do instead of creating the organization now.

        One of ``bind_org_creation_grant`` (confirm their approval from the Roboto web app), ``submit_access_request``,
        ``contact_deployment_administrator``, or ``use_web_app_session`` (sign in to Roboto in a browser, without acting
        as another user).
        """
        self.reason = reason
        """Reason for the refusal: ``org_creation_grant_bound_to_other_cognito_user``, or ``None``.

        Roboto sets it when the caller's approval is linked to a different sign-in, and leaves it ``None`` otherwise.
        """

    @property
    def http_status_code(self) -> int:
        return 403

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["error"]["next_step"] = self.next_step
        result["error"]["reason"] = self.reason
        return result


class RobotoThreadReadOnlyException(RobotoDomainException):
    """A message was sent to a thread with Roboto's AI that a conversation outside Roboto, such as in Slack, owns.

    Such a thread is mirrored into that conversation, so Roboto refuses new messages to it over the API, which would
    leave the mirror incomplete. Its ``origin`` names the owner, such as
    :py:attr:`~roboto.ai.agent_thread.ThreadOrigin.SLACK`. The caller can still read, cancel, and rate the thread,
    and forking it gives a copy that accepts messages. :py:meth:`~roboto.ai.agent_thread.AgentThread.send` and
    :py:meth:`~roboto.ai.agent_thread.AgentThread.send_text` raise it.

    Roboto responds with HTTP 403, but this is not a permission failure and does not subclass
    ``RobotoUnauthorizedException``: who the caller is does not change the answer, so offer to fork the thread rather
    than to sign in again.
    """

    @property
    def http_status_code(self) -> int:
        return 403


class RobotoAuthenticationFailureException(RobotoDomainException):
    """The caller's token is expired or malformed."""

    @property
    def http_status_code(self) -> int:
        return 401


class RobotoNotFoundException(RobotoDomainException):
    """A resource the request names does not exist, or the caller cannot see it."""

    @property
    def http_status_code(self) -> int:
        return 404


class RobotoDatasetNotFoundException(RobotoNotFoundException):
    """The dataset the request names does not exist, or the caller cannot see it."""


class RobotoDeviceNotFoundException(RobotoNotFoundException):
    """The device the request names does not exist, or the caller cannot see it."""


class RobotoFeatureNotAvailableException(RobotoDomainException):
    """The request uses a feature that is not enabled for the caller."""

    @property
    def http_status_code(self) -> int:
        return 403


class RobotoNotReadyException(RobotoDomainException):
    """The resource the request names exists but is not ready yet, such as a query whose results are still coming.

    :py:meth:`~roboto.query.QueryClient.get_query_results` raises it for a query whose results are not available yet,
    and reading :py:attr:`~roboto.domain.devices.Device.configurations` raises it for a device whose record has no
    ``universal_device_id``.
    """

    @property
    def http_status_code(self) -> int:
        return 404


class RobotoIllegalArgumentException(RobotoDomainException):
    """An argument or request parameter has a value Roboto or the SDK rejects."""

    @property
    def http_status_code(self) -> int:
        return 400


class RobotoInvalidRequestException(RobotoDomainException):
    """Roboto rejected the request as invalid, such as a request body that fails validation."""

    @property
    def http_status_code(self) -> int:
        return 400


class RobotoUnknownFieldAddressException(RobotoInvalidRequestException):
    """A ``roboto.experimental.topics.FieldAddress`` names a ``path`` or ``field_id`` the topic's schema lacks.

    ``get_data_as_record_batches`` of ``roboto.experimental.topics.Topic``, and the ``get_data`` and ``get_data_as_df``
    methods that call it, raise it for an address in ``fields_include`` or ``fields_exclude``.
    """


class RobotoNotImplementedException(RobotoDomainException):
    """The request asks for an operation this deployment of Roboto does not provide."""

    @property
    def http_status_code(self) -> int:
        return 501


class RobotoDeprecatedException(RobotoDomainException):
    """The request uses something Roboto has retired, such as a token in a format it no longer accepts.

    Its message says what to use instead, such as a newer SDK or a new token.
    """

    @property
    def http_status_code(self) -> int:
        return 400


class RobotoInvalidStateTransitionException(RobotoDomainException):
    """A resource cannot reach the state an operation needs from the state it is in.

    :py:meth:`~roboto.domain.custom_fields.CustomField.wait_to_be_ready` raises it for a custom field that fails or is
    deleted before it becomes ready, and :py:meth:`~roboto.domain.custom_fields.CustomField.wait_to_be_deleted` for
    one that was never deleted or whose deletion failed.
    """

    @property
    def http_status_code(self) -> int:
        return 400


class RobotoNoOrgProvidedException(RobotoDomainException):
    """The request needs an organization, the caller belongs to more than one, and the request named none."""

    @property
    def http_status_code(self) -> int:
        return 400


class RobotoConditionException(RobotoDomainException):
    """A condition the request depends on does not hold, such as the organization having an AI model it can use."""

    @property
    def http_status_code(self) -> int:
        return 409


class RobotoConflictException(RobotoDomainException):
    """The request conflicts with an existing resource, such as by giving a name another resource already has."""

    @property
    def http_status_code(self) -> int:
        return 409


class RobotoOrgEmailDomainChangeRefusedException(RobotoConflictException):
    """An organization's email domain cannot change as asked.

    :py:meth:`~roboto.domain.orgs.Org.bind_email_domain`,
    :py:meth:`~roboto.domain.orgs.Org.check_email_domain_verification`,
    :py:meth:`~roboto.domain.orgs.Org.new_email_domain_verification_record`,
    :py:meth:`~roboto.domain.orgs.Org.set_email_domain_auto_join` and
    :py:meth:`~roboto.domain.orgs.Org.start_email_domain_verification` raise it.
    """

    def __init__(
        self,
        message: str,
        reason: str,
        stack_trace: list[str] = [],
        headers: dict[str, str] = {},
        *args,
        **kwargs,
    ):
        super().__init__(message, stack_trace, headers, *args, **kwargs)
        self.reason = reason
        """Reason the email domain cannot change.

        One of the values of :py:class:`~roboto.domain.orgs.OrgEmailDomainChangeRefusal`, which describes each:
        ``dns_record_not_found``, ``held_by_another_org``, ``no_verification_challenge``, or
        ``not_verified_or_provisionally_approved``.
        """

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["error"]["reason"] = self.reason
        return result


@experimental
class RobotoBoardRevisionConflictException(RobotoConflictException):
    """A board update's ``base_revision`` no longer matches the board's revision.

    Someone changed the board's definition after the requester loaded the board, so applying the update could erase
    that change. ``current_board`` holds the board record as stored when Roboto refused the update, in its JSON form,
    so a client can show both versions and let the user resolve the conflict without another request.
    """

    def __init__(
        self,
        message: str,
        current_board: dict[str, Any],
        stack_trace: list[str] = [],
        headers: dict[str, str] = {},
        *args,
        **kwargs,
    ):
        super().__init__(message, stack_trace, headers, *args, **kwargs)
        self.current_board = current_board

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        # RobotoDomainException.from_json passes each envelope field to the constructor by name, so this key must match
        # the current_board parameter.
        result["error"]["current_board"] = self.current_board
        return result


class RobotoLayoutConflictException(RobotoConflictException):
    """Several layouts the caller can see have the name the request looks up, so the name alone picks none of them."""

    def __init__(
        self,
        message: str,
        conflicting_layouts: list[dict[str, Any]],
        stack_trace: list[str] = [],
        headers: dict[str, str] = {},
        *args,
        **kwargs,
    ):
        super().__init__(message, stack_trace, headers, *args, **kwargs)
        self.conflicting_layouts = conflicting_layouts
        """Records of the layouts that have the name, in their JSON form, so a client can ask which one was meant."""

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["error"]["conflicting_layouts"] = self.conflicting_layouts
        return result


@experimental
class RobotoDashboardRevisionConflictException(RobotoConflictException):
    """An update to a dashboard's definition names a base revision that no longer matches the dashboard's revision.

    Someone replaced the definition after the requester loaded it, so applying the update would erase that change.
    ``current_dashboard`` holds the dashboard record as stored when Roboto refused the update, in its JSON form, so a
    client can show both versions and let the user resolve the conflict without another request.
    """

    def __init__(
        self,
        message: str,
        current_dashboard: dict[str, Any],
        stack_trace: list[str] = [],
        headers: dict[str, str] = {},
        *args,
        **kwargs,
    ):
        super().__init__(message, stack_trace, headers, *args, **kwargs)
        self.current_dashboard = current_dashboard

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        # RobotoDomainException.from_json passes each envelope field to the constructor by name, so this key must match
        # the current_dashboard parameter.
        result["error"]["current_dashboard"] = self.current_dashboard
        return result


class RobotoServiceException(RobotoDomainException):
    """Roboto failed unexpectedly."""


class RobotoUnknownOperationException(RobotoDomainException):
    """The request names an API route Roboto does not serve."""

    @property
    def http_status_code(self) -> int:
        return 404


class RobotoExpiredException(RobotoDomainException):
    """The resource the request names is missing or has expired."""

    @property
    def http_status_code(self) -> int:
        return 410


class RobotoLimitExceededException(RobotoDomainException):
    """The request would take the user or organization past a limit on a resource, such as AI credits."""

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
        """Name of the limited resource, or ``"Unknown"`` when Roboto named none."""
        return self.__resource_name

    @property
    def limit_quantity(self) -> int:
        """Limit on the resource, in its own units, or 0 when Roboto reported none."""
        return self.__limit_quantity

    @property
    def current_quantity(self) -> int:
        """Quantity of the resource in use when Roboto refused the request, or 0 when Roboto reported none."""
        return self.__current_quantity

    def to_dict(self) -> dict[str, Any]:
        as_dict = super().to_dict()
        as_dict["error"]["resource_name"] = self.resource_name
        as_dict["error"]["current_quantity"] = self.current_quantity
        as_dict["error"]["limit_quantity"] = self.limit_quantity
        return as_dict


class RobotoFailedToGenerateException(RobotoDomainException):
    """Roboto failed to generate something the request asked for, such as an AI summary.

    The :py:class:`~roboto.ai.summary.StreamingAISummary` that
    :py:meth:`~roboto.domain.datasets.Dataset.generate_summary` and
    :py:meth:`~roboto.domain.datasets.Dataset.get_summary` return raises it from ``complete_text``,
    ``await_completion`` and ``text_stream`` when the summary fails.
    """

    @property
    def http_status_code(self) -> int:
        return 500


class RobotoInternalException(RobotoDomainException):
    """Roboto failed because of an error in its own code or data, which retrying is unlikely to fix.

    When Roboto reports one, its message gives no detail beyond a trace ID that Roboto support can use to find the
    failure.
    """

    @property
    def http_status_code(self) -> int:
        return 500


class ReadPlanExecutionErrorKind(StrEnum):
    """Reason a read of a topic's data through its read plan cannot continue.

    The ``kind`` of a ``RobotoReadPlanExecutionException``.
    """

    UNSUPPORTED_FORMAT = "unsupported-format"
    """A scan task stores its data in a format other than MCAP or Parquet, the formats the SDK decodes."""

    PLAN_WITHOUT_SCHEMA = "plan-without-schema"
    """The plan projects every field of its schema, has a partition with a scan task, and names no schema."""

    PROJECTED_FIELD_IN_NO_SCAN_TASK = "projected-field-in-no-scan-task"
    """No scan task of a partition reads the whole schema or a subtree containing a projected field."""

    FIELD_SPLIT_INSIDE_NON_STRUCT = "field-split-inside-non-struct"
    """A partition's files split a field that one of them stores as other than a struct, such as a list or a map."""

    INCONSISTENT_SCAN_TASKS_ON_FILE = "inconsistent-scan-tasks-on-file"
    """Scan tasks of one partition read one file but disagree on its format, transformations or topic name."""

    SCAN_TASK_ROW_MISMATCH = "scan-task-row-mismatch"
    """The files of a partition hold different rows in the window."""

    UNSUPPORTED_TIMESTAMP = "unsupported-timestamp"
    """The partition's timestamp is in a form the SDK cannot read.

    The form is one of: a timestamp kind the SDK does not know; a schema field with no path; a unit other than s, ms,
    us or ns; a message log or publish time on a Parquet file; or a Parquet timestamp field that sits inside a list or
    map, holds a DATE or TIME, or is not a number.
    """

    INVALID_TIMESTAMP = "invalid-timestamp"
    """A stored timestamp has no signed 64-bit nanosecond value once shifted by its partition's ``time_offset_ns``.

    It is NaN or infinite, a DECIMAL holding a fraction of a nanosecond, or out of range.
    """

    PARTITION_SCHEMA_MISMATCH = "partition-schema-mismatch"
    """A later partition's files give the read a different schema than the first partition's."""

    FIELD_NOT_IN_FILE = "field-not-in-file"
    """A file lacks a field the read takes from it: a field it supplies, or the partition's timestamp field."""

    DATA_RANGE_NOT_IN_FILE = "data-range-not-in-file"
    """A partition's ``data_range`` ends past its file's last stored row, so the file lacks rows the read needs."""

    ELEMENT_COUNT_MISMATCH = "element-count-mismatch"
    """A named array holds a different number of elements than it has names."""


class RobotoReadPlanExecutionException(RobotoInternalException):
    """A read of a topic's data through its read plan cannot continue; ``kind`` says why.

    A read plan is Roboto's description of which files hold a topic's data and how to decode them.
    ``get_data_as_record_batches`` of ``roboto.experimental.topics.Topic``, and the ``get_data`` and ``get_data_as_df``
    methods that call it, raise this while they read those files.
    """

    def __init__(
        self,
        message: str,
        stack_trace: list[str] = [],
        headers: dict[str, str] = {},
        *args,
        kind: ReadPlanExecutionErrorKind | str,
        field_path: Optional[collections.abc.Sequence[str]] = None,
        row_number: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(message, stack_trace, headers, *args, **kwargs)
        # A string kind comes from from_json, which rebuilds the exception from to_dict's output.
        self.__kind = ReadPlanExecutionErrorKind(kind)
        self.__field_path = tuple(field_path) if field_path is not None else None
        self.__row_number = row_number

    @property
    def kind(self) -> ReadPlanExecutionErrorKind:
        """Reason the read cannot continue."""
        return self.__kind

    @property
    def field_path(self) -> Optional[tuple[str, ...]]:
        """Path components of the field the error concerns, or ``None`` for kinds that concern no field.

        For ``ReadPlanExecutionErrorKind.FIELD_NOT_IN_FILE``, the missing field's path, from its top-level field down
        to the first component the file lacks. For ``ReadPlanExecutionErrorKind.ELEMENT_COUNT_MISMATCH``, the named
        array's path.
        """
        return self.__field_path

    @property
    def row_number(self) -> Optional[int]:
        """Position of the row the error concerns, from 0, among its topic's rows in its file, or ``None``.

        Set for ``ReadPlanExecutionErrorKind.INVALID_TIMESTAMP``, and for
        ``ELEMENT_COUNT_MISMATCH`` on a variable-length list. ``None`` for other kinds, and when a fixed-size list's
        width is refused before any row is read.
        """
        return self.__row_number

    def to_dict(self) -> dict[str, Any]:
        as_dict = super().to_dict()
        as_dict["error"]["kind"] = self.kind.value
        if self.field_path is not None:
            as_dict["error"]["field_path"] = list(self.field_path)
        if self.row_number is not None:
            as_dict["error"]["row_number"] = self.row_number
        return as_dict


class RobotoResponseTooLargeException(RobotoDomainException):
    """The response to the request is larger than Roboto can send.

    Retrying the same request fails the same way; request less data at a time.
    """

    @property
    def http_status_code(self) -> int:
        return 507


class RobotoServiceUnavailableException(RobotoDomainException):
    """Roboto could not accept the request, such as under heavy load. Retrying later may succeed."""

    @property
    def http_status_code(self) -> int:
        return 503


class RobotoServiceTimeoutException(RobotoDomainException):
    """Roboto ran out of time while processing the request. Retrying may succeed."""

    @property
    def http_status_code(self) -> int:
        return 504


class RobotoOperationTimeoutException(RobotoServiceTimeoutException):
    """Roboto stopped an operation, such as a search, that ran past its time limit. Retrying may succeed."""

    @property
    def http_status_code(self) -> int:
        return 504


class RobotoContextTooLongException(RobotoDomainException):
    """A conversation with Roboto's AI is longer than the AI model can read at once.

    The conversation's messages and tool results, together with the AI's instructions, exceed the model's context
    window. The exception does not carry the token count or the model's limit.
    """

    def __init__(
        self,
        message: str,
        stack_trace: list[str] = [],
        headers: dict[str, str] = {},
        # Roboto releases before 0.44.0 put estimated_tokens and max_tokens in the error envelope, and from_json
        # passes every envelope field to the constructor. Accepting and discarding them lets the SDK read the error
        # from such a deployment. Remove once every deployment runs 0.44.0 or later.
        estimated_tokens: int = 0,
        max_tokens: int = 0,
        *args,
        **kwargs,
    ):
        super().__init__(message, stack_trace, headers, *args, **kwargs)

    @property
    def http_status_code(self) -> int:
        return 400


class RobotoUnrecognizedErrorException(RobotoDomainException):
    """Roboto reported an error that this release of the SDK cannot match to a specific exception class.

    Reported for an element of a :py:class:`~roboto.http.BatchResponse` whose error names a code this release
    defines no class for, or that arrived without a code, without a message, or as text that is not an
    error envelope at all. It carries whatever code and message Roboto sent, so a caller handling the
    failure still learns what went wrong; when no message could be read, the message is the error's raw text.
    :py:meth:`~roboto.domain.devices.Device.create_session` raises it, and
    :py:meth:`~roboto.domain.devices.Device.create_sessions` lists it in the batch's
    :py:attr:`~roboto.http.BatchResponse.failed`.

    The error envelope carries no status code, so ``http_status_code`` reports the 500 inherited from
    ``RobotoDomainException`` rather than the status the failure had.
    """

    __error_code: Optional[str]

    def __init__(
        self,
        message: str,
        stack_trace: list[str] = [],
        headers: dict[str, str] = {},
        error_code: Optional[str] = None,
        *args,
        **kwargs,
    ):
        super().__init__(message, stack_trace, headers, *args, **kwargs)
        self.__error_code = error_code

    @property
    def error_code(self) -> str:
        """Code Roboto sent, or the name of this class when the error arrived without one."""
        return self.__error_code if self.__error_code is not None else self.__class__.__name__


class RobotoHttpExceptionParse(object):
    """Context manager that re-raises an HTTP error from its body as the matching Roboto exception.

    The request methods of :py:class:`~roboto.http.RobotoClient` wrap each request in it, so most code never uses it.
    It converts an :py:class:`~roboto.exceptions.HttpError` with
    ``RobotoDomainException.from_client_error`` and lets every other exception through unchanged.
    """

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        if issubclass(type(exception), HttpError):
            raise RobotoDomainException.from_client_error(error=exception) from None
