# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# This file is adapted from pandas.compat._optional.py
# https://github.com/pandas-dev/pandas/blob/2419343bfea5dba678146139ca9663d831c47b22/pandas/compat/_optional.py
# As of time of writing (2024-09-20), pandas is distributed under the terms of the BSD 3-Clause License,
# which can be found at:
# https://github.com/pandas-dev/pandas/blob/2419343bfea5dba678146139ca9663d831c47b22/LICENSE

import importlib
import types
import typing
import warnings

IMPORT_ERROR_MSG_TEMPLATE = (
    "Missing optional dependency '{module_name}'. "
    "Re-install roboto using pip or conda with 'roboto[{pip_extra}]' to install a compatible version."
)

KNOWN_PIP_EXTRAS: typing.TypeAlias = typing.Literal["analytics"]


@typing.overload
def import_optional_dependency(
    module_name: str,
    pip_extra: KNOWN_PIP_EXTRAS,
    *,
    errors: typing.Literal["raise"] = ...,
) -> types.ModuleType: ...


@typing.overload
def import_optional_dependency(
    module_name: str,
    pip_extra: KNOWN_PIP_EXTRAS,
    *,
    errors: typing.Literal["warn", "ignore"],
) -> types.ModuleType | None: ...


def import_optional_dependency(
    module_name: str,
    pip_extra: KNOWN_PIP_EXTRAS,
    *,
    errors: typing.Literal["raise", "warn", "ignore"] = "raise",
) -> types.ModuleType | None:
    """
    Import an optional dependency.

    By default, if a dependency is missing an ImportError with a nice
    message will be raised.

    Parameters
    ----------
    module_name : str
        The module name.
    pip_extra : str
        The pip extra to use in the ImportError message.
    errors : str {'raise', 'warn', 'ignore'}
        What to do when a dependency is not found or its version is too old.

        * raise : Raise an ImportError
        * ignore: If the module is not installed, return None, otherwise,
          return the module.
    Returns
    -------
    maybe_module : Optional[ModuleType]
        The imported module, when found.
        None is returned when the package is not found and `errors`
        is False, or when the package's version is too old and `errors`
        is ``'warn'`` or ``'ignore'``.
    """
    assert errors in {"raise", "warn", "ignore"}

    msg = IMPORT_ERROR_MSG_TEMPLATE.format(module_name=module_name, pip_extra=pip_extra)
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        if errors == "raise":
            raise ImportError(msg) from None

        if errors == "warn":
            warnings.warn(msg)

        return None

    return module
