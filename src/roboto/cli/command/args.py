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
    """Parse a flag value as JSON, read from the file it names or from the value itself, as an argparse ``type``.

    A value that names an existing file is replaced by that file's contents; any other value is parsed as JSON text.

    Args:
        arg: Value argparse read for the flag.

    Raises:
        argparse.ArgumentTypeError: The file's contents, or the value, are not valid JSON.
        OSError: The value names a file that cannot be read.
    """
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
        raise argparse.ArgumentTypeError("Could not interpret payload {} '{}' as JSON".format(arg_type, arg))


class KeyValuePairsAction(argparse.Action):
    """Argparse action that collects ``KEY=VALUE`` flag values into a dictionary.

    Pass this class as ``action=`` to ``add_argument``. Each value splits at its first ``=``, so a value may itself
    contain ``=``. By default, a value that parses as JSON is stored parsed (``count=3`` stores the integer ``3``)
    and any other value stays a string; passing ``parse_json=False`` to ``add_argument`` keeps every value a string.
    Pairs from repeated uses of the flag merge into one dictionary, and a later pair replaces an earlier one with the
    same key.

    Raises:
        SystemExit: A value has no ``=``. ``parser.error`` prints the usage text and the reason to stderr.
    """

    def __init__(self, option_strings, dest, parse_json=True, **kwargs):
        self.parse_json = parse_json
        self.value_dict = {}
        super().__init__(option_strings, dest, **kwargs)

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
            # Without nargs, argparse passes a single string instead of a list.
            if isinstance(values, str):
                values = [values]

            for pair in values:
                parts = pair.split("=", 1)
                if len(parts) != 2:
                    raise ValueError(
                        f"Expected format 'KEY=VALUE', got '{pair}'. Make sure the argument contains an '=' sign."
                    )
                key, value = parts

                parsed_value = value
                if self.parse_json:
                    try:
                        parsed_value = json.loads(value)
                    except json.decoder.JSONDecodeError:
                        pass

                self.value_dict[key] = parsed_value

            setattr(namespace, self.dest, self.value_dict)
        except Exception as e:
            # Any failure, such as a pair with no '=', ends parsing: parser.error prints the usage and this message,
            # then exits with status 2.
            raise parser.error(f"Failed to parse '{self.dest}' argument '{values}': {e}")


def ExistingPathlibPath(arg):
    """Build a ``pathlib.Path`` from a flag value, as an argparse ``type``, rejecting a path that does not exist.

    Args:
        arg: Value argparse read for the flag.

    Raises:
        argparse.ArgumentTypeError: Nothing exists at the path.
    """
    path = pathlib.Path(arg)
    if not path.exists():
        raise argparse.ArgumentTypeError(f"Provided path '{arg}' does not exist!")
    return path


def NonBlankString(arg: str) -> str:
    """Reject an empty or whitespace-only flag value, as an argparse ``type``.

    A blank value ends argument parsing with ``error: argument <flag>: may not be blank``.

    Args:
        arg: Value argparse read for the flag.

    Returns:
        ``arg`` exactly as given, including any leading or trailing whitespace.

    Raises:
        argparse.ArgumentTypeError: The value is empty or consists only of whitespace.
    """
    if not arg.strip():
        raise argparse.ArgumentTypeError("may not be blank")
    return arg
