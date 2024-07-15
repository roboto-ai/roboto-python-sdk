# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic


def remove_non_noneable_init_args(data: dict, model: pydantic.BaseModel) -> dict:
    """
    Remove keys from `data` (e.g., kwargs passed to `__init__`) set to `None`
    that are not allowed to be `None` according to `model`'s type definition.

    This is particularly useful when marshalling data from the database into a
    Pydantic model. If a database row has a `NULL` value for a
    field that is not nullable, this function can be used to filter out those `None`
    values before passing the data to the model's `__init__` method.

    Example usage:

    >>> class Foo(pydantic.BaseModel):
    ...     a: int = 3
    ...     def __init__(self, **kwargs):
    ...         filtered_kwargs = remove_non_noneable_init_args(kwargs, self)
    ...         super().__init__(**filtered_kwargs)
    ...
    >>> Foo(a=None)
    Foo(a=3, b='bar')

    Without this function, the above would raise a `ValidationError`.
    """

    def _field_allows_none(field_name):
        field = model.model_fields.get(field_name)
        if field is None:
            return False

        # Allows none if field annotation is a union type and None is one of the types in the union
        try:
            # After dropping 3.9 support, add `isinstance(field.annotation, types.UnionType)`
            # to this statement to remove the `# type: ignore` and ditch the try/except.
            return type(None) in field.annotation.__args__  # type: ignore
        except AttributeError:
            return False

    return {k: v for k, v in data.items() if v is not None or _field_allows_none(k)}


def validate_nonzero_gitpath_specs(value: list[str]) -> list[str]:
    filtered = list(filter(lambda p: p.strip() != "", value))

    if len(value) == 0:
        raise ValueError("Paths must not be empty.")
    elif len(filtered) == 0:
        raise ValueError(
            "Paths must have at least one entry which is not the empty string or just whitespace."
        )

    return value
