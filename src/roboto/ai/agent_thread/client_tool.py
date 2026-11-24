# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import inspect
import re
import typing
from typing import Any, Optional, Union

import pydantic
import pydantic.fields

from .record import ClientToolSpec


class ClientTool:
    """A client tool together with the Python function that runs it when Roboto's AI requests the tool.

    Pass client tools to :py:meth:`~roboto.ai.agent_thread.AgentThread.start` or
    :py:meth:`~roboto.ai.agent_thread.AgentThread.send` as ``client_tools``, or add one to a thread with
    :py:meth:`~roboto.ai.agent_thread.AgentThread.register_client_tool`. When the AI requests the tool,
    :py:meth:`~roboto.ai.agent_thread.AgentThread.run` calls the function with the AI's input as keyword arguments and
    submits what it returns: a dictionary as it is, ``None`` as an empty dictionary, and any other value as
    ``{"result": <value>}``. If the function raises an exception, ``run`` submits the exception's type and message as
    an error result instead.

    Most callers build a client tool with ``client_tool`` or ``from_function``, which infer the input schema from the
    function's type hints and docstring. A tool's name must match ``^client_[a-z][a-z0-9_]*$``, so name the function
    ``client_<name>`` or pass ``name``.

    Args:
        fn: Function to call when the AI requests the tool.
        name: Name of the tool, which the AI uses to request it.
        description: Human-readable description of what the tool does, which the AI reads to decide when to use it.
        input_schema: JSON Schema of the tool's input.

    Raises:
        pydantic.ValidationError: ``name`` does not match ``^client_[a-z][a-z0-9_]*$``.
    """

    def __init__(
        self,
        fn: collections.abc.Callable[..., Any],
        *,
        name: str,
        description: str,
        input_schema: dict[str, Any],
    ) -> None:
        self._fn = fn
        self._spec = ClientToolSpec(
            name=name,
            description=description,
            input_schema=input_schema,
        )

    @classmethod
    def from_function(
        cls,
        fn: collections.abc.Callable[..., Any],
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        input_schema: Optional[dict[str, Any]] = None,
    ) -> ClientTool:
        """Build a client tool from a Python function.

        Each parameter of ``fn`` becomes a property of the inferred input schema. Its description comes from the
        ``Args:`` section of ``fn``'s docstring, unless the parameter's type hint is
        ``typing.Annotated[T, pydantic.Field(description="...")]`` or its default is
        ``pydantic.Field(description="...")``, which take precedence. Only a section headed ``Args:`` is read.

        Args:
            fn: Function to call when the AI requests the tool.
            name: Name of the tool, which the AI uses to request it. ``None`` uses ``fn.__name__``.
            description: Human-readable description of what the tool does, which the AI reads to decide when to use
                it. ``None`` uses ``fn``'s docstring up to its first section header, such as ``Args:``.
            input_schema: JSON Schema of the tool's input. ``None`` infers it from ``fn``'s signature, type hints, and
                docstring.

        Raises:
            ValueError: The description is empty, because ``description`` is empty or is ``None`` and ``fn`` has no
                docstring text before its first section header; or ``input_schema`` is ``None`` and ``fn`` takes
                ``*args`` or ``**kwargs``.
            pydantic.ValidationError: The tool's name does not match ``^client_[a-z][a-z0-9_]*$``.
            pydantic.errors.PydanticSchemaGenerationError: ``input_schema`` is ``None`` and a parameter's type hint
                has no JSON Schema form, such as a class that is not a pydantic model or dataclass.

        Examples:
            Take the parameter's description from ``Annotated`` instead of the docstring:

            >>> from typing import Annotated
            >>> from pydantic import Field
            >>> def client_recall(
            ...     query: Annotated[str, Field(description="Substring to search for.")],
            ... ) -> str:
            ...     \"\"\"Search long-term memory.\"\"\"
            ...     ...
            >>> tool = ClientTool.from_function(client_recall)

            Set the name and description explicitly:

            >>> def store(fact: str) -> str: ...
            >>> tool = ClientTool.from_function(
            ...     store,
            ...     name="client_store_fact",
            ...     description="Store a fact in long-term memory.",
            ... )
            >>> tool.name
            'client_store_fact'
        """
        resolved_name = fn.__name__ if name is None else name
        summary, param_descriptions = _split_google_docstring(inspect.getdoc(fn))
        resolved_description = summary if description is None else description
        if not resolved_description:
            raise ValueError(
                f"ClientTool {resolved_name!r} requires a description; "
                "pass description=... or add a docstring to the function."
            )
        resolved_schema = input_schema if input_schema is not None else _infer_schema(fn, param_descriptions)
        return cls(
            fn,
            name=resolved_name,
            description=resolved_description,
            input_schema=resolved_schema,
        )

    @property
    def spec(self) -> ClientToolSpec:
        """Specification of the tool, which the SDK sends to Roboto so that Roboto offers the tool to the AI."""
        return self._spec

    @property
    def name(self) -> str:
        """Name of the tool, which the AI uses to request it.

        See :py:attr:`~roboto.ai.agent_thread.ClientToolSpec.name` for the form a name must take.
        """
        return self._spec.name

    def __call__(self, **kwargs: Any) -> Any:
        """Call the tool's function with these keyword arguments and return its result."""
        return self._fn(**kwargs)


# These overloads only tell type checkers which call form returns what: client_tool(fn) and a bare @client_tool
# return a ClientTool, and client_tool(name=...) returns a decorator that does. Without them, the declared return
# type is the union of both, and `tool = client_tool(fn); tool.name` fails type checking.
@typing.overload
def client_tool(fn: collections.abc.Callable[..., Any], /) -> ClientTool: ...


@typing.overload
def client_tool(
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    input_schema: Optional[dict[str, Any]] = None,
) -> collections.abc.Callable[[collections.abc.Callable[..., Any]], ClientTool]: ...


def client_tool(
    fn: Optional[collections.abc.Callable[..., Any]] = None,
    /,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    input_schema: Optional[dict[str, Any]] = None,
) -> Union[ClientTool, collections.abc.Callable[[collections.abc.Callable[..., Any]], ClientTool]]:
    """Build a ``ClientTool`` from a function, as a decorator or a direct call.

    Use it bare (``@client_tool``) to infer the tool's name, description, and input schema from the function, or with
    keyword arguments (``@client_tool(name="...")``) to set some of them. Either way, the decorated name holds the
    ``ClientTool``. ``ClientTool.from_function`` builds the tool and says how each value is inferred; the exceptions it
    lists also apply, raised when the decorator is applied to the function.

    Args:
        fn: Function to build the tool from. ``None`` returns a decorator that takes it.
        name: Name of the tool, which the AI uses to request it. ``None`` uses the function's name.
        description: Human-readable description of what the tool does, which the AI reads to decide when to use it.
            ``None`` uses the function's docstring up to its first section header, such as ``Args:``.
        input_schema: JSON Schema of the tool's input. ``None`` infers it from the function's signature, type hints,
            and docstring.

    Returns:
        The client tool, or, when ``fn`` is ``None``, a decorator that builds one from the function it decorates.

    Examples:
        Infer everything from the function, including each parameter's description from its docstring's ``Args:``
        section:

        >>> @client_tool
        ... def client_remember(fact: str) -> str:
        ...     \"\"\"Store a fact in long-term memory.
        ...
        ...     Args:
        ...         fact: A standalone sentence worth remembering.
        ...     \"\"\"
        ...     ...

        Set the name and description explicitly:

        >>> @client_tool(name="client_store_fact", description="Persist a fact.")
        ... def store(fact: str) -> str: ...
        >>> store.name
        'client_store_fact'
    """

    def wrap(f: collections.abc.Callable[..., Any]) -> ClientTool:
        return ClientTool.from_function(
            f,
            name=name,
            description=description,
            input_schema=input_schema,
        )

    if fn is not None:
        return wrap(fn)
    return wrap


def _infer_schema(
    fn: collections.abc.Callable[..., Any],
    param_descriptions: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Build a JSON Schema of a function's parameters with pydantic.

    A parameter takes its description from ``param_descriptions`` unless its type hint or default already declares a
    non-empty one with ``pydantic.Field(description=...)``.
    """
    if param_descriptions is None:
        param_descriptions = {}

    sig = inspect.signature(fn)
    fields: dict[str, Any] = {}
    for pname, param in sig.parameters.items():
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            raise ValueError(
                f"Cannot infer schema for {fn.__name__}: parameter {pname!r} is *args. "
                "Pass input_schema=... explicitly or refactor the function to accept named parameters."
            )
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            raise ValueError(
                f"Cannot infer schema for {fn.__name__}: parameter {pname!r} is **kwargs. "
                "Pass input_schema=... explicitly or refactor the function to accept named parameters."
            )
        annotation: Any = param.annotation if param.annotation is not inspect.Parameter.empty else Any
        default: Any = param.default if param.default is not inspect.Parameter.empty else ...

        doc_description = param_descriptions.get(pname)
        if doc_description and not _has_description(annotation, default):
            annotation = typing.Annotated[annotation, pydantic.Field(description=doc_description)]

        fields[pname] = (annotation, default)

    model = pydantic.create_model(f"{fn.__name__}__ClientToolInput", **fields)
    return model.model_json_schema()


def _has_description(annotation: Any, default: Any) -> bool:
    """Return whether the parameter's type hint or default declares a non-empty ``pydantic.Field`` description.

    An empty description counts as none, so the docstring's description of the parameter still fills the schema.
    """
    for meta in typing.get_args(annotation):
        if isinstance(meta, pydantic.fields.FieldInfo) and meta.description:
            return True
    if isinstance(default, pydantic.fields.FieldInfo) and default.description:
        return True
    return False


# ---------------------------------------------------------------------------
# Google-style docstring parsing.
#
# Reads only what a client tool needs: the text before the first section header, which becomes the tool's
# description, and the parameter descriptions in the Args: section. Everything else in the docstring is ignored.
# ---------------------------------------------------------------------------

_ARGS_HEADER_RE = re.compile(r"^Args:\s*$")
"""Regular expression an ``Args:`` section header line must match, unindented and case-sensitive."""

_PARAM_LINE_RE = re.compile(r"^(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$")
"""Regular expression a parameter line must match: ``name: description`` or ``name (type): description``.

The type, if present, is ignored.
"""

_SECTION_HEADER_RE = re.compile(
    r"^("
    r"Args|Arguments|Attributes|"
    r"Example|Examples|"
    r"Hint|Important|"
    r"Keyword Args|Keyword Arguments|"
    r"Note|Notes|"
    r"Other Parameters|Parameters|"
    r"Raises|References|Returns|See Also|Tip|Todo|"
    r"Warning|Warnings|Warns|Yields"
    r"):\s*$"
)
"""Regular expression any Google-style section header line must match.

It covers every Google-style section name, so that no section placed before ``Args:`` ends up in the tool
description the AI reads.
"""


def _split_google_docstring(docstring: Optional[str]) -> tuple[str, dict[str, str]]:
    """Split a Google-style docstring into its text before the first section header and its parameter descriptions.

    Returns:
        ``(summary, param_descriptions)``: the text before the first section header, stripped of surrounding
        whitespace, and a map from parameter name to description, empty when there is no ``Args:`` section.
    """
    if not docstring:
        return "", {}

    lines = docstring.splitlines()
    section_starts: list[int] = [i for i, line in enumerate(lines) if _SECTION_HEADER_RE.match(line)]

    if section_starts:
        summary = "\n".join(lines[: section_starts[0]]).strip()
    else:
        summary = docstring.strip()

    return summary, _parse_args_section(lines)


def _parse_args_section(lines: list[str]) -> dict[str, str]:
    """Parse the ``Args:`` section into a map from parameter name to description.

    The first parameter line sets the indent every later parameter line must have. Lines indented deeper than that
    continue the previous parameter's description and are joined to it with single spaces. The section ends at an
    unindented section header, at the end of the docstring, or at any other line, so that prose after the section
    never becomes part of a description.

    Returns ``{}`` when there is no ``Args:`` section.
    """
    try:
        start = next(i for i, line in enumerate(lines) if _ARGS_HEADER_RE.match(line)) + 1
    except StopIteration:
        return {}

    params: dict[str, str] = {}
    current_name: Optional[str] = None
    current_chunks: list[str] = []
    param_indent: Optional[int] = None

    def flush() -> None:
        if current_name is not None:
            params[current_name] = " ".join(chunk.strip() for chunk in current_chunks if chunk.strip())

    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and _SECTION_HEADER_RE.match(stripped):
            break
        if param_indent is None or indent == param_indent:
            match = _PARAM_LINE_RE.match(stripped)
            if match:
                flush()
                current_name = match.group(1)
                current_chunks = [match.group(2)]
                param_indent = indent
                continue
        if current_name is not None and param_indent is not None and indent > param_indent:
            current_chunks.append(stripped)
            continue
        break

    flush()
    return params


__all__ = [
    "ClientTool",
    "client_tool",
]
