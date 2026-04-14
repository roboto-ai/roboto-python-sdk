# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import functools
import typing
import warnings


def roboto_default_warning_behavior():
    # https://github.com/boto/botocore/issues/619
    warnings.filterwarnings(
        "ignore",
        module="botocore.vendored.requests.packages.urllib3.connectionpool",
        message=".*",
    )


class ExperimentalWarning(Warning):
    """Warning issued when an experimental API is used.

    Experimental APIs may be incomplete, subject to change, or removed without notice.

    Users can suppress these warnings with::

        import warnings
        from roboto import ExperimentalWarning

        warnings.filterwarnings("ignore", category=ExperimentalWarning)
    """


_F = typing.TypeVar("_F", bound=typing.Callable[..., typing.Any])

_DEFAULT_MESSAGE = "{name} is experimental and may change or be removed without notice."

_SPHINX_NOTICE = ".. warning:: **Experimental**: {message}\n\n"


@typing.overload
def experimental(target: type) -> type: ...


@typing.overload
def experimental(target: _F) -> _F: ...


@typing.overload
def experimental(target: str) -> typing.Callable[[typing.Union[type, _F]], typing.Union[type, _F]]: ...


@typing.overload
def experimental(*, message: str) -> typing.Callable[[typing.Union[type, _F]], typing.Union[type, _F]]: ...


def experimental(
    target: typing.Union[type, _F, str, None] = None,
    *,
    message: typing.Optional[str] = None,
) -> typing.Any:
    """Mark a class, function, or method as experimental.

    Experimental APIs may be incomplete, subject to change, or removed without notice.
    When called, the decorated target emits an :class:`ExperimentalWarning`.

    Can be used in three ways::

        @experimental
        def my_function(): ...


        @experimental("Custom message about this API.")
        def my_function(): ...


        @experimental(message="Custom message about this API.")
        def my_function(): ...
    """

    def _decorate(obj: typing.Any, msg: str) -> typing.Any:
        if isinstance(obj, type):
            return _decorate_class(obj, msg)
        if callable(obj):
            return _decorate_callable(obj, msg)
        raise TypeError(f"@experimental cannot be applied to {type(obj)}")

    # @experimental (bare, no parentheses) — target is the decorated object
    if target is not None and not isinstance(target, str):
        msg = _DEFAULT_MESSAGE.format(name=getattr(target, "__qualname__", str(target)))
        return _decorate(target, msg)

    # @experimental("message") or @experimental(message="message")
    custom_message = target if isinstance(target, str) else message

    def decorator(obj: typing.Any) -> typing.Any:
        if custom_message:
            msg = custom_message
        else:
            msg = _DEFAULT_MESSAGE.format(name=getattr(obj, "__qualname__", str(obj)))
        return _decorate(obj, msg)

    return decorator


def _prepend_sphinx_notice(obj: typing.Any, msg: str) -> None:
    notice = _SPHINX_NOTICE.format(message=msg)
    existing = obj.__doc__ or ""
    obj.__doc__ = notice + existing


def _decorate_class(cls: type, msg: str) -> type:
    # Wrap __new__ rather than __init__ to avoid mypy soundness error [misc]
    # ("Accessing '__init__' on an instance is unsound"). This mirrors the
    # approach used by CPython's warnings.deprecated (PEP 702) and the
    # `deprecated` PyPI package.
    original_new = cls.__new__
    has_custom_new = original_new is not object.__new__

    def warned_new(target_cls: type, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        if target_cls is cls:
            warnings.warn(msg, ExperimentalWarning, stacklevel=2)
        if has_custom_new:
            return original_new(target_cls, *args, **kwargs)
        return object.__new__(target_cls)

    cls.__new__ = staticmethod(warned_new)  # type: ignore[assignment]
    _prepend_sphinx_notice(cls, msg)
    return cls


def _decorate_callable(fn: _F, msg: str) -> _F:
    @functools.wraps(fn)
    def wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        warnings.warn(msg, ExperimentalWarning, stacklevel=2)
        return fn(*args, **kwargs)

    _prepend_sphinx_notice(wrapper, msg)
    return typing.cast(_F, wrapper)
