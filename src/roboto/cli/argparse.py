# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
from operator import attrgetter
import typing


class DeprecationAction(argparse.Action):
    """An action that triggers a deprecation error."""

    __deprecation_msg: typing.Optional[str] = None

    def __init__(
        self,
        option_strings,
        dest,
        help=None,
        deprecation_msg: typing.Optional[str] = None,
        **kwargs,
    ):
        super(DeprecationAction, self).__init__(
            option_strings, dest, nargs=0, help=help, **kwargs
        )
        self.__deprecation_msg = deprecation_msg

    def __call__(self, parser, namespace, values, option_string=None):
        deprecation_msg = (
            self.__deprecation_msg
            if self.__deprecation_msg
            else f"Deprecated option: {option_string}"
        )
        parser.error(deprecation_msg)


class SortingHelpFormatter(argparse.HelpFormatter):
    def add_arguments(self, actions):
        actions = sorted(actions, key=attrgetter("option_strings"))
        super(SortingHelpFormatter, self).add_arguments(actions)
