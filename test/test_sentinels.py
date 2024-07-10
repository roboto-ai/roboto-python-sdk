# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional, Union

from pydantic import (
    BaseModel,
    PositiveInt,
    ValidationError,
)
from pytest import raises

from roboto.sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)


class MyModel(BaseModel):
    value: Optional[Union[PositiveInt, NotSetType]] = NotSet


def test_union_type_does_not_default_to_notset():
    # Arrange/Act

    # Assert
    with raises(ValidationError):
        MyModel(value=-42)

    # Assert
    model = MyModel(value=42)
    assert model.value == 42

    # Assert
    model = MyModel()
    assert model.value == NotSet

    # Assert
    model = MyModel(value=None)
    assert model.value is None


def test_not_set_clears_model_dump():
    assert remove_not_set(MyModel(value=NotSet)).model_dump(exclude_unset=True) == {}
    assert remove_not_set(MyModel(value=10)).model_dump(exclude_unset=True) == {
        "value": 10
    }
    assert remove_not_set(MyModel(value=None)).model_dump(exclude_unset=True) == {
        "value": None
    }
