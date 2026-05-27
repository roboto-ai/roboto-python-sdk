# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import logging
from types import SimpleNamespace
import typing
import weakref

_log = logging.getLogger(__name__)

_APPLIED_MARKER = "_roboto_mcap_ros2_class_cache_applied"


def apply() -> bool:
    """Patch ``mcap_ros2._dynamic._read_complex_type`` to cache the dynamic message class.

    The upstream function rebuilds a ``SimpleNamespace`` subclass on every call and
    computes ``str(msgdef)`` (which walks every field of the schema) as part of that
    class body. For workloads that decode tens of thousands of messages of a nested
    schema, the result is millions of redundant class constructions and schema
    stringifications. The patch caches the constructed class under ``id(msgdef)`` and
    registers a :py:func:`weakref.finalize` callback on every cached ``msgdef`` so the
    entry evicts before the source object's address can be recycled. Without this,
    a later schema landing at a recycled address would silently inherit the previous
    class's ``_type``, ``_full_text``, and captured dunders.
    (``MessageSpecification`` defines ``__eq__`` without ``__hash__`` and is therefore
    unhashable, so a :py:class:`weakref.WeakKeyDictionary` can't be used directly.)

    Returns ``True`` when the patch is applied (including subsequent idempotent calls),
    ``False`` when skipped because the upstream module shape no longer matches what
    this patch expects.

    The patch should be removed once the equivalent fix lands in mcap-ros2-support
    upstream and the floor in ``pyproject.toml`` is raised past that release.
    """
    try:
        import mcap_ros2._dynamic as dynamic_mod
    except ImportError:
        return False

    if getattr(dynamic_mod, _APPLIED_MARKER, False):
        return True

    required_attrs = ("_read_complex_type", "FIELD_PARSERS", "ARRAY_PARSERS", "CdrReader")
    missing = [a for a in required_attrs if not hasattr(dynamic_mod, a)]
    if missing:
        # The patch reaches into private internals; if upstream renames or removes any
        # of them, skip rather than corrupt module state. This lets us bump
        # mcap-ros2-support without code changes once upstream ships the fix.
        _log.warning(
            "Skipping mcap_ros2 class cache: upstream _dynamic module is missing %s",
            missing,
        )
        return False

    patched = _build_patched_read_complex_type(dynamic_mod)
    dynamic_mod._read_complex_type = patched
    dynamic_mod.read_message = _build_patched_read_message(dynamic_mod, patched)
    setattr(dynamic_mod, _APPLIED_MARKER, True)
    _log.info("Applied mcap_ros2 class cache")
    return True


def _build_patched_read_complex_type(dynamic_mod: typing.Any) -> typing.Callable:
    class_cache: dict[int, type] = {}
    repr_fn = dynamic_mod.__repr__
    eq_fn = dynamic_mod.__eq__
    ne_fn = dynamic_mod.__ne__
    field_parsers = dynamic_mod.FIELD_PARSERS
    array_parsers = dynamic_mod.ARRAY_PARSERS

    def read_complex_type(msgdef, msgdefs, reader):
        cache_key = id(msgdef)
        Msg = class_cache.get(cache_key)
        if Msg is None:
            Msg = type(
                msgdef.msg_name,
                (SimpleNamespace,),
                {
                    "__name__": msgdef.msg_name,
                    "__slots__": [field.name for field in msgdef.fields],
                    "__repr__": repr_fn,
                    "__str__": repr_fn,
                    "__eq__": eq_fn,
                    "__ne__": ne_fn,
                    "_type": str(msgdef.base_type),
                    "_full_text": str(msgdef),
                },
            )
            # Evict the entry before the address can be recycled; otherwise a later
            # msgdef allocated at the same id would silently reuse this class.
            weakref.finalize(msgdef, class_cache.pop, cache_key, None)
            class_cache[cache_key] = Msg

        msg = Msg()

        if len(msgdef.fields) == 0:
            # ROS 2 IDL adds a `uint8 structure_needs_at_least_one_member` field to
            # any otherwise-empty message; consume the byte.
            reader.uint8()

        for field in msgdef.fields:
            ftype = field.type
            if not ftype.is_primitive_type():
                nested = msgdefs.get(f"{ftype.pkg_name}/{ftype.type}")
                if nested is None:
                    raise ValueError(f'Message definition not found for field "{field.name}" with type "{ftype.type}"')
                if ftype.is_array:
                    array_length = (
                        ftype.array_size
                        if ftype.is_fixed_size_array() and ftype.array_size is not None
                        else reader.uint32()
                    )
                    value = [read_complex_type(nested, msgdefs, reader) for _ in range(array_length)]
                else:
                    value = read_complex_type(nested, msgdefs, reader)
                setattr(msg, field.name, value)
            else:
                if ftype.is_array:
                    array_parser_fn = array_parsers.get(ftype.type)
                    if array_parser_fn is None:
                        raise NotImplementedError(f"Parsing for type {ftype.type}[] is not implemented")
                    array_length = (
                        ftype.array_size
                        if ftype.is_fixed_size_array() and ftype.array_size is not None
                        else reader.sequence_length()
                    )
                    value = array_parser_fn(reader, array_length)
                else:
                    parser_fn = field_parsers.get(ftype.type)
                    if parser_fn is None:
                        raise NotImplementedError(f"Parsing for type {ftype.type} is not implemented")
                    value = parser_fn(reader)
                setattr(msg, field.name, value)

        return msg

    # Exposed for tests so they can assert finalize-driven eviction without reaching
    # into closure cells.
    read_complex_type._class_cache = class_cache  # type: ignore[attr-defined]
    return read_complex_type


def _build_patched_read_message(dynamic_mod: typing.Any, patched_read_complex_type: typing.Callable) -> typing.Callable:
    cdr_reader_cls = dynamic_mod.CdrReader

    def read_message(schema_name, msgdefs, data):
        msgdef = msgdefs.get(schema_name)
        if msgdef is None:
            raise ValueError(f'Message definition not found for "{schema_name}"')
        return patched_read_complex_type(msgdef, msgdefs, cdr_reader_cls(data))

    return read_message
