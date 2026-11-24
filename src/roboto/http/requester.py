# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import platform
import typing

import pydantic

from ..compat import StrEnum

try:
    from ..version import (
        __version__ as roboto_version,
    )
except ModuleNotFoundError:
    roboto_version = "0.0.0"


class RobotoTool(StrEnum):
    """Roboto tool a request is sent from, as recorded in ``RobotoRequester.roboto_tool``."""

    Cli = "cli"
    """Roboto CLI."""

    Sdk = "sdk"
    """Roboto Python SDK."""

    UploadAgent = "upload-agent"
    """Roboto Upload Agent."""

    Website = "website"
    """Roboto web app."""


class RobotoRequester(pydantic.BaseModel):
    """Description of the program sending a request to Roboto: the tool, its version, and the operating system.

    A client set up with :py:meth:`~roboto.http.HttpClient.set_requester` sends it as JSON in the
    ``ROBOTO_REQUESTER_HEADER`` header of every request, so Roboto can tell which tools, versions and operating systems
    send requests, which helps debug them. Building one with a ``schema_version`` other than
    ``"v1"`` raises ``pydantic.ValidationError``.
    """

    schema_version: typing.Literal["v1"] = "v1"
    """Format of the payload, always ``"v1"``."""

    platform: typing.Optional[str] = None
    """Environment the request is sent from, or ``None`` when the sender does not report it.

    For a request from a browser, this is the browser's user agent. For a request from the SDK, it is the result of
    Python's ``platform.platform()``.
    """

    roboto_tool: typing.Optional[typing.Union[RobotoTool, str]] = None
    """Roboto tool the request is sent from, or ``None`` when it does not come from a Roboto tool."""

    roboto_tool_version: typing.Optional[str] = None
    """Version of the tool named in ``roboto_tool``, or ``None`` when the sender does not report it."""

    roboto_tool_details: typing.Optional[str] = None
    """Free-text details about the tool named in ``roboto_tool``, or ``None`` when there are none."""

    @classmethod
    def for_tool(cls, tool: RobotoTool) -> "RobotoRequester":
        """Build the requester for a Roboto tool that sends requests through this SDK.

        :py:meth:`~roboto.http.RobotoClient.from_env`, the CLI and the Upload Agent describe themselves through it, so
        most code never calls it. It reports the operating system from ``platform.platform()`` and, as the tool's
        version, the installed SDK's version.

        Args:
            tool: Roboto tool the requests are sent from.
        """

        return RobotoRequester(
            schema_version="v1",
            platform=platform.platform(),
            roboto_tool=tool.value,
            roboto_tool_version=roboto_version,
            roboto_tool_details=None,
        )


ROBOTO_REQUESTER_HEADER = "X-Roboto-Requester"
"""Header naming the program that sends the request, as a ``RobotoRequester`` in JSON.

Roboto ignores a value it cannot parse and handles the request as if the header were absent.
"""
