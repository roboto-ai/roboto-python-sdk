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
    """A client-side tool with an execution callback.

    Wraps a Python callable as a tool that the Roboto agent can request the
    client to execute. The tool's JSON schema is inferred from the callable's
    type hints; the tool description and per-parameter descriptions are taken
    from the function's Google-style docstring unless passed explicitly.

    Most callers build ClientTools via the :py:func:`client_tool` decorator
    or :py:meth:`ClientTool.from_function` rather than instantiating this
    class directly.

    Examples:
        Using the decorator — descriptions come from the docstring:

        >>> @client_tool
        ... def remember(fact: str, tags: Optional[list[str]] = None) -> str:
        ...     \"\"\"Store a fact in long-term memory.
        ...
        ...     Args:
        ...         fact: A standalone sentence worth remembering.
        ...         tags: Optional tags for later retrieval.
        ...     \"\"\"
        ...     ...

        Using ``Annotated[T, Field(...)]`` instead (takes precedence over the
        docstring):

        >>> from typing import Annotated
        >>> from pydantic import Field
        >>> @client_tool
        ... def recall(
        ...     query: Annotated[str, Field(description="Substring to search for.")],
        ... ) -> str:
        ...     \"\"\"Search long-term memory.\"\"\"
        ...     ...

        Using the factory with explicit overrides:

        >>> tool = ClientTool.from_function(
        ...     my_fn,
        ...     name="store_fact",
        ...     description="Store a fact in long-term memory.",
        ... )
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
        """Build a ClientTool from a Python callable.

        The tool's name defaults to ``fn.__name__``. The tool description
        defaults to the summary-and-body of ``fn``'s docstring (everything
        before the first Google-style section header like ``Args:`` or
        ``Returns:``). Per-parameter descriptions are pulled from the
        docstring's ``Args:`` section, and can be overridden with
        ``typing.Annotated[T, pydantic.Field(description="...")]`` or
        ``param: T = pydantic.Field(description="...")``.

        Args:
            fn: The callable to invoke when the tool is dispatched.
            name: Override for the tool name (default: ``fn.__name__``).
            description: Override for the tool description (default: the
                docstring's summary-and-body). Required if ``fn`` has no
                docstring.
            input_schema: Override for the input JSON Schema (default:
                inferred from ``fn``'s type hints and docstring).

        Returns:
            A ClientTool wrapping the given callable.

        Raises:
            ValueError: If the description cannot be resolved, or if
                ``input_schema`` is not provided and the signature cannot be
                automatically converted (e.g. uses ``*args`` or ``**kwargs``).
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
        """Declarative spec sent to the Roboto backend."""
        return self._spec

    @property
    def name(self) -> str:
        """Tool name surfaced to the LLM."""
        return self._spec.name

    def __call__(self, **kwargs: Any) -> Any:
        """Invoke the underlying callable with keyword arguments."""
        return self._fn(**kwargs)


# The two overloads below exist purely for type-checker precision; they have no
# runtime effect. ``client_tool`` supports two call shapes:
#
#   1. Bare:       ``@client_tool`` / ``client_tool(fn)``  -> ClientTool
#   2. With args:  ``@client_tool(name="...")``            -> decorator that
#                                                             returns ClientTool
#
# The implementation's real return type is the union of those, which is accurate
# but unhelpful at call sites -- e.g. ``tool = client_tool(fn); tool.name`` would
# fail type-checking because the ``Callable[..., ClientTool]`` arm of the union
# has no ``.name`` attribute. The overloads let mypy / Pyright discriminate by
# call shape: passing a function positionally resolves to ``ClientTool``;
# calling with only keyword arguments resolves to the inner decorator. Either
# way, the final decorated name ends up typed as ``ClientTool`` without the
# caller having to narrow the union manually.
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
    """Decorator that converts a function into a :class:`ClientTool`.

    Usable bare (``@client_tool``) or with keyword overrides
    (``@client_tool(description="...")``). See :py:meth:`ClientTool.from_function`
    for how descriptions are resolved.

    Note:
        This function is declared with two :py:func:`typing.overload` stubs
        above so that type checkers see the decorated name as a
        :class:`ClientTool` regardless of call form. The overloads carry no
        runtime behavior; the implementation below handles both shapes.

    Examples:
        Bare — infers everything from the function, including per-parameter
        descriptions from the docstring's ``Args:`` section:

        >>> @client_tool
        ... def remember(fact: str) -> str:
        ...     \"\"\"Store a fact in long-term memory.
        ...
        ...     Args:
        ...         fact: A standalone sentence worth remembering.
        ...     \"\"\"
        ...     ...

        With overrides:

        >>> @client_tool(name="store_fact", description="Persist a fact.")
        ... def _store(fact: str) -> str: ...
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
    """Derive a JSON Schema for a function's parameters using pydantic.

    Descriptions from the ``param_descriptions`` map are injected into each
    field unless the parameter already has a description via
    ``Annotated[T, Field(description=...)]`` or ``Field(description=...)`` as a
    default value — those always take precedence over the docstring.
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
    """Return True iff a non-empty description is already declared on the field.

    A ``Field(description="")`` is treated as absent so the docstring fallback
    can still populate the schema — mirrors the ``if doc_description and ...``
    check in :func:`_infer_schema`.
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
# This is deliberately a small, opinionated parser for the subset of
# Google-style docstrings Roboto uses: a summary-and-body paragraph followed by
# section headers like ``Args:`` / ``Returns:`` / ``Raises:``. We don't lean on
# a dependency for this — the surface is tight enough that a targeted parser is
# clearer than teaching a general-purpose one what we do and don't care about.
# ---------------------------------------------------------------------------

_ARGS_HEADER_RE = re.compile(r"^Args:\s*$")
"""Matches the ``Args:`` section header (line-anchored, case-sensitive)."""

_PARAM_LINE_RE = re.compile(r"^(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$")
"""Matches ``name: description`` or ``name (type): description`` (type ignored)."""

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
"""Matches any Google-style section header that terminates a preceding block.

Kept deliberately broad so sections between the summary body and ``Args:`` do
not leak into the tool description the LLM sees.
"""


def _split_google_docstring(docstring: Optional[str]) -> tuple[str, dict[str, str]]:
    """Split a Google-style docstring into (summary, {param: description}).

    The summary is everything before the first section header (``Args``,
    ``Returns``, etc.), stripped of surrounding whitespace. The param
    description map comes from the ``Args:`` section; if absent, it is empty.
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
    """Parse the ``Args:`` section into a param-name -> description map.

    Param lines are expected at a consistent indent below the ``Args:`` header
    (typically 4 spaces). Continuation lines indented deeper than the param
    line are joined onto its description with single spaces. The section ends
    at the next Google-style section header (at column 0), at any unrecognized
    non-matching line, or at EOF.

    Returns ``{}`` if no ``Args:`` section is present.
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
        # A section header at column 0 ends the Args section.
        if indent == 0 and _SECTION_HEADER_RE.match(stripped):
            break
        # A param line — either the first one (establishes param_indent) or
        # one at the established indent.
        if param_indent is None or indent == param_indent:
            match = _PARAM_LINE_RE.match(stripped)
            if match:
                flush()
                current_name = match.group(1)
                current_chunks = [match.group(2)]
                param_indent = indent
                continue
        # A continuation of the previous param's description (indented deeper).
        if current_name is not None and param_indent is not None and indent > param_indent:
            current_chunks.append(stripped)
            continue
        # Anything else (unrecognized line at or below the param indent): bail
        # to avoid silently consuming unrelated prose.
        break

    flush()
    return params


__all__ = [
    "ClientTool",
    "client_tool",
]
