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
        values: str | collections.abc.Sequence[typing.Any] | None,
        option_string: str | None = None,
    ):
        if values is None:
            return

        try:
            for pair in values:
                key, value = pair.split("=")
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
