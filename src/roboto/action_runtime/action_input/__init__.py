# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Resolution of an action invocation's input selectors to files, sessions and topics, and access to them from code.

An action's code reads its input as an :py:class:`~roboto.action_runtime.action_input.ActionInput`, from
:py:meth:`~roboto.action_runtime.InvocationContext.get_input`.
:py:class:`~roboto.action_runtime.action_input.ActionInputResolver` finds what the selectors of an
:py:class:`~roboto.domain.actions.InvocationInput` match and can download the files; Roboto runs it while it sets up
an invocation that has input, before the action's code starts.
"""

from .action_input import (
    DEFAULT_INPUT_FILE,
    ActionInput,
    ActionInputRecord,
)
from .file_resolver import InputFileResolver
from .input_resolver import ActionInputResolver
from .session_resolver import InputSessionResolver
from .topic_resolver import InputTopicResolver

__all__ = (
    "DEFAULT_INPUT_FILE",
    "ActionInput",
    "ActionInputRecord",
    "ActionInputResolver",
    "InputFileResolver",
    "InputSessionResolver",
    "InputTopicResolver",
)
