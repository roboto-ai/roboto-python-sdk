# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

import pytest

from roboto.cli.common_args import (
    ActionParameterArg,
)
from roboto.domain import actions


@pytest.mark.parametrize(
    ["param_string", "expected"],
    [
        (
            "name=my_param|required=true|description=My description",
            actions.ActionParameter(
                name="my_param",
                required=True,
                description="My description",
            ),
        ),
        (
            "name=my_param|required=false|description=My description|default=default value",
            actions.ActionParameter(
                name="my_param",
                required=False,
                description="My description",
                default="default value",
            ),
        ),
        (
            "description=My description   | name=my_param |default=default value|  required=true | ",
            actions.ActionParameter(
                name="my_param",
                required=True,
                description="My description",
                default="default value",
            ),
        ),
        (
            (
                "default=default value, with cool punction--yes!|description=My description. More punctuation."
                "|name=my-param $%^!@#&|required=false"
            ),
            actions.ActionParameter(
                name="my-param $%^!@#&",
                required=False,
                description="My description. More punctuation.",
                default="default value, with cool punction--yes!",
            ),
        ),
    ],
)
def test_action_parameter_parsing(param_string: str, expected: actions.ActionParameter):
    # Arrange
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--parameter",
        metavar=ActionParameterArg.METAVAR,
        nargs="*",
        action=ActionParameterArg,
    )
    expectation = expected if isinstance(expected, list) else [expected]

    # Act
    args = parser.parse_args(
        [
            "--parameter",
            param_string,
        ]
    )

    # Assert
    assert args.parameter == expectation


def test_action_parameter_parsing_deals_with_multiple() -> None:
    # Arrange
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--parameter",
        metavar=ActionParameterArg.METAVAR,
        nargs="*",
        action=ActionParameterArg,
    )

    # Act
    args = parser.parse_args(
        [
            "--parameter",
            "name=my_param_1",
            "--parameter",
            "name=my_param_2|description=A verbose description, here is. Yup.",
            "--parameter",
            "name=my_param_3|default=default value",
        ]
    )

    expection = [
        actions.ActionParameter(
            name="my_param_1",
        ),
        actions.ActionParameter(
            name="my_param_2",
            description="A verbose description, here is. Yup.",
        ),
        actions.ActionParameter(
            name="my_param_3",
            default="default value",
        ),
    ]

    # Assert
    assert args.parameter == expection
