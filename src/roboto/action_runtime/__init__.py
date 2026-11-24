# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tools for an action's code to use while an invocation of the action runs.

Use :py:class:`~roboto.action_runtime.InvocationContext`, which replaces the deprecated
:py:class:`~roboto.action_runtime.ActionRuntime`, to read the invocation's parameters, secrets, and input data, and to
set tags and metadata on the files the action writes to its output directory.
"""

from .action_input import (
    ActionInput,
    ActionInputResolver,
)
from .exceptions import (
    ActionRuntimeException,
    PrepareEnvException,
)
from .exit_codes import ExitCode
from .file_changeset import (
    FilesChangesetFileManager,
)
from .invocation_context import (
    ActionRuntime,
    InvocationContext,
)
from .prepare import (
    prepare_invocation_input_data,
    prepare_invocation_parameters,
    prepare_metadata_changeset_manifest,
)

__all__ = (
    "ActionInput",
    "ActionInputResolver",
    "ActionRuntime",
    "ActionRuntimeException",
    "ExitCode",
    "FilesChangesetFileManager",
    "InvocationContext",
    "PrepareEnvException",
    "prepare_invocation_input_data",
    "prepare_invocation_parameters",
    "prepare_metadata_changeset_manifest",
)
