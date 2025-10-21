# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from .exit_codes import ExitCode


class ActionRuntimeException(Exception):
    """
    Base class for all exceptions raised by the action_runtime submodule.
    """


class PrepareEnvException(ActionRuntimeException):
    exit_code: ExitCode
    reason: str

    def __init__(self, exit_code: ExitCode, reason: str):
        super().__init__()
        self.exit_code = exit_code
        self.reason = reason

    def __str__(self) -> str:
        return f"{self.reason} (Exit code {self.exit_code})"
