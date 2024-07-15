# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import contextlib
import typing

import pydantic

from .terminal import print_error_and_exit


class pydantic_validation_handler(contextlib.AbstractContextManager):
    """
    Context manager to catch Pydantic validation errors and print the first error neatly to stderr.
    """

    __parseable_name: str = "Roboto model"

    def __init__(self, parseable_name: typing.Optional[str] = None):
        if parseable_name is not None:
            self.__parseable_name = parseable_name

    def __enter__(self):
        pass

    def __exit__(self, exctype, excinst, exctb):
        if exctype is None:
            return

        if issubclass(exctype, pydantic.ValidationError):
            first_error, *_rest = excinst.errors()
            msg = first_error.get("msg")
            loc = first_error.get("loc", tuple())
            if loc:
                path_to_error = ".".join([str(key_path) for key_path in loc])
                msg = f"'{path_to_error}' {msg}"

            error_msg = [f"Error parsing {self.__parseable_name}"]
            if msg:
                error_msg.append(msg)

            print_error_and_exit(error_msg)

        return False
