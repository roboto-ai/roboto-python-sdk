# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from roboto.pydantic import (
    remove_non_noneable_init_args,
)


def test_remove_non_noneable_init_args() -> None:
    # Arrange
    class Foo(pydantic.BaseModel):
        a: int = 3
        b: str = "bar"
        c: typing.Union[bool, None] = None
        d: typing.Optional[int] = None

        def __init__(self, **kwargs):
            filtered_kwargs = remove_non_noneable_init_args(kwargs, self)
            super().__init__(**filtered_kwargs)

    # Act
    actual = Foo.model_validate(
        {
            "a": None,
            "b": None,
            "c": None,
            "d": None,
        }
    )

    # Assert
    assert actual == Foo()
