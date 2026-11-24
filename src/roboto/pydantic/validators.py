# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic


def remove_non_noneable_init_args(data: dict, model: pydantic.BaseModel) -> dict:
    """Return ``data`` without the ``None`` values that ``model``'s fields do not accept.

    Call it from a model's ``__init__`` so that a ``None`` passed for a field whose type excludes ``None`` falls back
    to the field's default instead of failing validation. A field accepts ``None`` only when its annotation is a union
    that includes ``None``, such as ``typing.Optional[str]``; a field annotated ``typing.Any`` does not count. A
    ``None`` for a key that names no field of ``model`` is removed too.

    Args:
        data: Keyword arguments passed to the model's ``__init__``. It is not modified.
        model: Model whose field annotations decide which ``None`` values to keep, usually the instance being built.

    Examples:
        Without the filter, ``Foo(a=None)`` raises ``pydantic.ValidationError``:

        >>> class Foo(pydantic.BaseModel):
        ...     a: int = 3
        ...
        ...     def __init__(self, **kwargs):
        ...         super().__init__(**remove_non_noneable_init_args(kwargs, self))
        >>> Foo(a=None)
        Foo(a=3)
    """

    def _field_allows_none(field_name):
        field = model.model_fields.get(field_name)
        if field is None:
            return False

        # An annotation with no type arguments, such as int, has no __args__; the AttributeError means the
        # field does not accept None.
        try:
            return type(None) in field.annotation.__args__  # type: ignore
        except AttributeError:
            return False

    return {k: v for k, v in data.items() if v is not None or _field_allows_none(k)}


def validate_nonzero_gitpath_specs(value: list[str]) -> list[str]:
    """Reject a list of gitignore-style patterns that is empty or holds only blank strings.

    Args:
        value: Patterns to check.

    Returns:
        ``value``, unchanged.

    Raises:
        ValueError: ``value`` is empty, or every pattern in it is empty or only whitespace.
    """
    filtered = list(filter(lambda p: p.strip() != "", value))

    if len(value) == 0:
        raise ValueError("Paths must not be empty.")
    elif len(filtered) == 0:
        raise ValueError("Paths must have at least one entry which is not the empty string or just whitespace.")

    return value
