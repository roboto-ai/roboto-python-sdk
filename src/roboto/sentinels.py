# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing
from typing import TypeGuard

import pydantic

T = typing.TypeVar("T")
"""Type of the value a function in this module takes or returns."""

PydanticModel = typing.TypeVar("PydanticModel", bound=pydantic.BaseModel)
"""Type of the pydantic model that a function in this module reads.

The functions that read one are ``remove_not_set`` and ``is_any_set``.
"""


class Null:
    """Type of ``null``: a command-line argument a user wrote as ``null`` to clear a field.

    Its one instance is falsy, and its ``repr`` is ``null``. The ``roboto`` command line checks for it with ``is``, so
    use ``null`` rather than constructing another.
    """

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "null"


null = Null()
"""Value ``maybe_null`` returns in place of a command-line argument a user wrote as ``null`` to clear a field."""


def maybe_null(value: T) -> typing.Union[T, Null]:
    """Return ``null`` when ``value`` is the string ``"null"`` in any case, else ``value``.

    The ``roboto`` command line converts each argument that can clear a field through it, so most code never calls
    it. That is how ``--description null`` clears a dataset's description.

    Args:
        value: Command-line argument to convert.
    """

    if isinstance(value, str) and value.lower() == "null":
        return null

    return value


class NotSetType(pydantic.BaseModel):
    """Type of ``NotSet``: a field or argument the caller did not set.

    An update request defaults a field to ``NotSet``, so that a field left out is unchanged while ``None`` clears it.
    ``NotSet`` is falsy. It is a pydantic model with no fields, so a request model can hold it in a field; a model dump
    writes it as ``{}``, and ``remove_not_set`` leaves such fields out. Use ``NotSet`` rather than constructing
    another; constructing one with any arguments raises ``ValueError``.
    """

    def __init__(self, **data):
        if len(data) > 0:
            raise ValueError(f"Unexpected data: {data} passed into NotSetType")

        super().__init__(**data)

    @staticmethod
    def openapi_schema_modifier(schema: dict[str, typing.Any], model: typing.Any) -> None:
        """Rewrite a model's JSON schema so that each field that accepts ``NotSet`` shows as nullable instead.

        Pydantic calls this while it builds the JSON schema of a model whose config sets
        ``json_schema_extra=NotSetType.openapi_schema_modifier``. In each property's ``anyOf``, it replaces each
        reference to ``NotSetType`` with ``{"type": "null"}``, and it drops the property's default of ``{}``, which is
        ``NotSet`` as a model dump writes it.

        Args:
            schema: JSON schema of the model, changed in place.
            model: Ignored.
        """
        for prop in schema.get("properties", {}).values():
            if "anyOf" in prop:
                any_of = prop.pop("anyOf")

                without_notset = []
                for sub_prop in any_of:
                    if isinstance(sub_prop, dict) and "NotSetType" in sub_prop.get("$ref", ""):
                        if "default" in prop and prop["default"] == {}:
                            del prop["default"]
                        without_notset.append({"type": "null"})
                    else:
                        without_notset.append(sub_prop)

                if without_notset:
                    if len(without_notset) == 1:
                        prop.update(without_notset[0])
                    else:
                        prop["anyOf"] = without_notset

    def __bool__(self) -> bool:
        return False


def is_not_set(value: typing.Any) -> TypeGuard[NotSetType]:
    """Return whether ``value`` is ``NotSet``.

    A type checker narrows ``value`` to ``NotSetType`` where this returns ``True``.

    Args:
        value: Value to check.
    """
    return isinstance(value, NotSetType)


def is_set(value: typing.Union[T, NotSetType]) -> TypeGuard[T]:
    """Return whether ``value`` is anything other than ``NotSet``, ``None`` included.

    A type checker narrows ``value`` to its type other than ``NotSetType`` where this returns ``True``.

    Args:
        value: Value to check.
    """
    return not isinstance(value, NotSetType)


def value_or_not_set(value: typing.Optional[T]) -> typing.Union[T, NotSetType]:
    """Return ``value``, or ``NotSet`` when it is ``None``.

    Use it to pass an optional argument to an update request field, where ``None`` would clear the field.

    Args:
        value: Value to pass on.
    """
    if value is None:
        return NotSet
    else:
        return value


def value_or_default_if_unset(value: typing.Union[T, NotSetType], default: T) -> T:
    """Return ``value``, or ``default`` when ``value`` is ``NotSet``.

    Args:
        value: Value that may be ``NotSet``.
        default: Value to return in its place.
    """
    if isinstance(value, NotSetType):
        return default
    else:
        return value


def remove_not_set(value: PydanticModel) -> PydanticModel:
    """Build a copy of a pydantic model on which the fields holding ``NotSet`` are unset.

    ``model_dump(exclude_unset=True)`` on the copy leaves those fields out, where a dump of the original writes each
    as ``{}``. Every other field is set on the copy, including one left at a default of ``None``, so the dump includes
    it. Only the model's own fields are checked, not those of models nested in it. Building the copy runs the model's
    validators again.

    Args:
        value: Model to copy.
    """
    set_args: dict[typing.Any, typing.Any] = {k: v for k, v in dict(value).items() if is_set(v)}
    return value.model_validate(set_args)


def is_any_set(value: PydanticModel) -> bool:
    """Return whether any field of a pydantic model holds a value other than ``NotSet``.

    A field holding ``None`` counts as set, so this returns ``True`` for any model with a field that defaults to
    ``None``.

    Args:
        value: Model to check.
    """
    for _, v in dict(value).items():
        if is_set(v):
            return True

    return False


NotSet = NotSetType()
"""Value of a field or argument the caller did not set, where ``None`` has a meaning of its own, such as clearing it."""
