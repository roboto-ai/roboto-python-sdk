# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum
import platform
import typing

import pydantic

from ..version import (
    __version__ as roboto_version,
)


class RobotoTool(str, enum.Enum):
    Cli = "cli"
    Sdk = "sdk"
    UploadAgent = "upload-agent"
    Website = "website"


class RobotoRequester(pydantic.BaseModel):
    """
    Details about the entity making a request to Roboto. These are embedded in a header in order to see what tool
    versions / operating systems are making requests, and to aid debugging.
    """

    schema_version: typing.Literal["v1"] = "v1"
    """Roboto Requester payload schema version, used to ensure backward compatibility"""

    platform: typing.Optional[str] = None
    """The environment in which a request is being made, i.e. the user agent (for browser requests) or the results
    of platform.platform (for SDK requests)"""

    roboto_tool: typing.Optional[typing.Union[RobotoTool, str]] = None
    """If a request is being made from a Roboto vended tool, the name of the tool"""

    roboto_tool_version: typing.Optional[str] = None
    """If a request is being made from a Roboto vended tool, the version of the tool"""

    roboto_tool_details: typing.Optional[str] = None
    """If a request is being made from a Roboto vended tool, free text pertinent details about the tool"""

    @classmethod
    def for_tool(cls, tool: RobotoTool) -> "RobotoRequester":
        """
        Called to intelligently populate a :class:`~RobotoRequester` for a request made from a named Roboto tool
        using the Python SDK.
        """

        return RobotoRequester(
            schema_version="v1",
            platform=platform.platform(),
            roboto_tool=tool.value,
            roboto_tool_version=roboto_version,
            roboto_tool_details=None,
        )


ROBOTO_REQUESTER_HEADER = "X-Roboto-Requester"
"""A JSON serialized :class:`~RobotoRequester` representing the entity making a request to Roboto."""
