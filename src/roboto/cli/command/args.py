# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import collections.abc
import json
import os
import pathlib
import typing


def JsonFileOrStrType(arg):
    arg_type = "string"

    if os.path.isfile(arg):
        arg_type = "file"
        with open(arg, "r") as f:
            payload = f.read()
    else:
        payload = arg

    try:
        return json.loads(payload)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "Could not interpret payload {} '{}' as JSON".format(arg_type, arg)
        )


class KeyValuePairsAction(argparse.Action):
    value_dict: dict[str, typing.Any] = {}

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: typing.Union[str, collections.abc.Sequence[typing.Any], None],
        option_string: typing.Union[str, None] = None,
    ):
        if values is None:
            return

        try:
            # Normalize to list if single string (when using nargs and parameter is not specified or nargs is 1)
            if isinstance(values, str):
                values = [values]

            for pair in values:
                # Use maxsplit=1 to handle values that contain '=' characters
                parts = pair.split("=", 1)
                if len(parts) != 2:
                    raise ValueError(
                        f"Expected format 'KEY=VALUE', got '{pair}'. "
                        f"Make sure the argument contains an '=' sign."
                    )
                key, value = parts

                if key in self.value_dict:
                    raise parser.error(
                        f"Key '{key}' was defined multiple times for '{self.dest}'"
                    )
                # Attempt to parse the value to better handle numbers, booleans, etc
                parsed_value = value
                try:
                    parsed_value = json.loads(value)
                except json.decoder.JSONDecodeError:
                    pass  # swallow
                self.value_dict[key] = parsed_value

            setattr(namespace, self.dest, self.value_dict)
        except Exception as e:
            raise parser.error(
                f"Failed to parse '{self.dest}' argument '{values}': {e}"
            )


def ExistingPathlibPath(arg):
    path = pathlib.Path(arg)
    if not path.exists():
        raise argparse.ArgumentTypeError(f"Provided path '{arg}' does not exist!")
    return path
