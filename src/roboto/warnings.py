# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing
import warnings


def roboto_default_warning_behavior():
    """Ignore every warning raised from the urllib3 connection pool that botocore vendors.

    Roboto calls this when ``roboto`` is imported. The filter applies to the whole Python process.
    """
    # The vendored pool warns `Connection pool is full, discarding connection` when more threads share one client
    # than the pool holds connections for. The warning is harmless.
    warnings.filterwarnings(
        "ignore",
        module="botocore.vendored.requests.packages.urllib3.connectionpool",
        message=".*",
    )


class ExperimentalWarning(Warning):
    """Warning category for experimental SDK APIs.

    Unused: nothing in the SDK emits or subclasses this warning. ``experimental`` marks an API as experimental in its
    docstring instead.
    """


_T = typing.TypeVar("_T")
_C = typing.TypeVar("_C", bound=type)
_F = typing.TypeVar("_F", bound=typing.Callable[..., typing.Any])

_DEFAULT_MESSAGE = "{name} is experimental and may change or be removed without notice."

_SPHINX_NOTICE = ".. warning:: **Experimental**: {message}\n\n"


@typing.overload
def experimental(target: _C, /) -> _C: ...


@typing.overload
def experimental(target: _F, /) -> _F: ...


@typing.overload
def experimental(target: str, /) -> typing.Callable[[_T], _T]: ...


@typing.overload
def experimental(*, message: str) -> typing.Callable[[_T], _T]: ...


def experimental(
    target: typing.Any = None,
    *,
    message: typing.Optional[str] = None,
) -> typing.Any:
    """Mark a class, function, or method as experimental.

    The SDK's own code uses it. Experimental APIs may be incomplete, subject to change, or removed without notice.

    Prepends a ``.. warning::`` notice to the target's docstring, so documentation rendered from it and ``help()``
    show the target as experimental, then returns the target itself. Apply it bare (``@experimental``), with the
    notice text as its argument (``@experimental("...")``), or with the notice text as ``message``
    (``@experimental(message="...")``).

    Args:
        target: Object to mark when applied bare, or the notice text when called as ``@experimental("...")``.
        message: Notice text. Defaults to ``"<qualified name of the target> is experimental and may change or be
            removed without notice."``

    Raises:
        TypeError: The target is not callable, as when the decorator is placed above ``@property`` or
            ``@classmethod`` and not below it. When notice text is passed, it is raised when the returned decorator
            is called.
    """
    # @experimental (bare, no parentheses): target is the decorated object
    if target is not None and not isinstance(target, str):
        return _prepend_sphinx_notice(target, None)

    # @experimental("message") or @experimental(message="message")
    custom_message = target if isinstance(target, str) else message

    def decorator(obj: typing.Any) -> typing.Any:
        return _prepend_sphinx_notice(obj, custom_message)

    return decorator


def _prepend_sphinx_notice(obj: typing.Any, custom_message: typing.Optional[str]) -> typing.Any:
    if not callable(obj):
        raise TypeError(f"@experimental cannot be applied to {type(obj)}")
    message = custom_message or _DEFAULT_MESSAGE.format(name=getattr(obj, "__qualname__", str(obj)))
    obj.__doc__ = _SPHINX_NOTICE.format(message=message) + (obj.__doc__ or "")
    return obj
