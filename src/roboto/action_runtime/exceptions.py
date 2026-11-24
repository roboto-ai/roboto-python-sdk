# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from .exit_codes import ExitCode


class ActionRuntimeException(Exception):
    """Base class of the exceptions the SDK raises when an action's environment lacks what the action asks for.

    These methods of :py:class:`~roboto.action_runtime.InvocationContext` raise it:

    - :py:meth:`~roboto.action_runtime.InvocationContext.from_env`, when a required environment variable is unset, or
      the input or output directory it names does not exist.
    - :py:attr:`~roboto.action_runtime.InvocationContext.dataset`, when the invocation has no dataset, as when the
      action runs locally, from a scheduled trigger, or from the CLI with query-based input data.
    - :py:meth:`~roboto.action_runtime.InvocationContext.get_input`, when the environment names no input manifest.
    - :py:meth:`~roboto.action_runtime.InvocationContext.get_parameter` and
      :py:meth:`~roboto.action_runtime.InvocationContext.get_secret_parameter`, when the parameter has no value.
    - :py:meth:`~roboto.action_runtime.InvocationContext.get_optional_parameter` and the two methods above, when the
      file that holds the parameters or secrets cannot be read or does not hold a JSON object.

    Outside Roboto's hosted compute environment, these usually mean the environment variables and files Roboto
    provides to an action were not set up. ``PrepareEnvException`` is the subclass raised while Roboto sets up an
    invocation.
    """


class PrepareEnvException(ActionRuntimeException):
    """Roboto could not prepare an invocation's parameters or input data while setting up the invocation.

    :py:func:`~roboto.action_runtime.prepare_invocation_parameters` raises it when a secret parameter names a secret
    that does not exist or that the invocation cannot read, and
    :py:func:`~roboto.action_runtime.prepare_invocation_input_data` raises it when the invocation's input data cannot
    be resolved. Roboto calls both when it sets up an invocation, and ``roboto actions invoke-local`` calls both to run
    an action on your computer. Roboto logs ``reason`` and ends the setup with ``exit_code``.
    """

    exit_code: ExitCode
    """Exit code the invocation's setup ends with."""

    reason: str
    """What went wrong, as a message for the invocation's logs."""

    def __init__(self, exit_code: ExitCode, reason: str):
        super().__init__()
        self.exit_code = exit_code
        self.reason = reason

    def __str__(self) -> str:
        return f"{self.reason} (Exit code {self.exit_code})"
