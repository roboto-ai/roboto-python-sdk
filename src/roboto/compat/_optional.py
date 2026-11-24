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
"""Message ``import_optional_dependency`` gives for a missing module, with ``module_name`` and ``pip_extra`` fields."""

KNOWN_PIP_EXTRAS: typing.TypeAlias = typing.Literal["analytics", "ingestion", "video"]
"""Extras of the ``roboto`` package that install optional dependencies, as in ``pip install roboto[<extra>]``."""


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
) -> typing.Union[types.ModuleType, None]: ...


def import_optional_dependency(
    module_name: str,
    pip_extra: KNOWN_PIP_EXTRAS,
    *,
    errors: typing.Literal["raise", "warn", "ignore"] = "raise",
) -> typing.Union[types.ModuleType, None]:
    """Import a module that one of the ``roboto`` package's extras installs.

    Args:
        pip_extra: Extra that installs the module, named in the message about a missing module.
        errors: What to do when the module cannot be imported. ``"raise"`` raises ``ImportError``, ``"warn"`` issues
            a ``UserWarning`` and returns ``None``, and ``"ignore"`` returns ``None``.

    Returns:
        The imported module, or ``None`` when it cannot be imported and ``errors`` is ``"warn"`` or ``"ignore"``.

    Raises:
        ImportError: The module cannot be imported and ``errors`` is ``"raise"``. Its message is
            ``IMPORT_ERROR_MSG_TEMPLATE``, formatted with ``module_name`` and ``pip_extra``.
        ValueError: The module cannot be imported and ``errors`` is not ``"raise"``, ``"warn"``, or ``"ignore"``.
    """
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        msg = IMPORT_ERROR_MSG_TEMPLATE.format(module_name=module_name, pip_extra=pip_extra)

        if errors == "raise":
            raise ImportError(msg) from None

        if errors == "warn":
            warnings.warn(msg)
            return None

        if errors == "ignore":
            return None

        raise ValueError(f"Expected errors to be one of 'raise', 'warn', 'ignore', got '{errors}'")

    return module
