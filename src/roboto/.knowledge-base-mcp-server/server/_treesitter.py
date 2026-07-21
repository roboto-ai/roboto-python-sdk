"""Shared tree-sitter setup and TS/JS symbol helpers.

Initializes language grammars once at import time so that ``chunkers``,
``indexer``, and ``tools`` share a single set of parsers and extraction
utilities.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tree_sitter import Node

_languages: dict[str, Any] = {}

_JSDOC_STAR_RE = re.compile(r"\s*\*\s*")
_JSDOC_TAG_RE = re.compile(r"\s@")

try:
    import tree_sitter as _ts
    import tree_sitter_javascript as _ts_js
    import tree_sitter_typescript as _ts_ts

    _languages["typescript"] = _ts.Language(_ts_ts.language_typescript())
    _languages["tsx"] = _ts.Language(_ts_ts.language_tsx())
    _languages["javascript"] = _ts.Language(_ts_js.language())
except Exception:
    _ts = None  # type: ignore[assignment]
    print(
        "tree-sitter not available — TS/JS/TSX files will use plain-text chunking",
        file=sys.stderr,
    )

LANG_FOR_EXT: dict[str, str] = {
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".mts": "typescript",
    ".cts": "typescript",
}


def parse(content: str, path: Path) -> Any | None:
    """Parse *content* with tree-sitter and return the syntax tree.

    Returns ``None`` when tree-sitter is unavailable or the file extension
    is not recognised.
    """
    lang_key = LANG_FOR_EXT.get(path.suffix)
    if lang_key is None:
        return None
    return parse_language(content, lang_key)


def parse_language(content: str, lang_key: str) -> Any | None:
    """Parse *content* using the named language grammar.

    *lang_key* should be one of ``"typescript"``, ``"tsx"``, or
    ``"javascript"``.  Returns ``None`` when tree-sitter is unavailable or
    the language key is unrecognised.
    """
    if _ts is None:
        return None
    if lang_key not in _languages:
        return None
    try:
        parser = _ts.Parser(_languages[lang_key])
        return parser.parse(content.encode())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# TS/JS symbol helpers — shared by indexer and tools
# ---------------------------------------------------------------------------

DECL_TYPES = {
    "function_declaration",
    "class_declaration",
    "interface_declaration",
    "type_alias_declaration",
    "enum_declaration",
    "lexical_declaration",
    "export_statement",
}

# Types ranked by descriptive priority (lower is better).
RANKED_TYPES = {
    "class_declaration": 0,
    "interface_declaration": 0,
    "type_alias_declaration": 1,
    "enum_declaration": 1,
    "function_declaration": 2,
    "lexical_declaration": 2,
}


def node_text(node: Node, source: bytes) -> str:
    """Return the source text for a tree-sitter *node*."""
    return source[node.start_byte : node.end_byte].decode()


def unwrap_export(node: Node) -> Node:
    """Return the declaration inside an ``export_statement``, or *node* itself."""
    if node.type == "export_statement":
        for child in node.children:
            if child.type in RANKED_TYPES:
                return child
    return node


def symbol_name(node: Node, source: bytes) -> str:
    """Extract the declared name from a declaration node."""
    actual = unwrap_export(node)
    name_node = actual.child_by_field_name("name")
    if name_node:
        return node_text(name_node, source)
    for child in actual.children:
        if child.type == "variable_declarator":
            n = child.child_by_field_name("name")
            if n:
                return node_text(n, source)
    return ""


def jsdoc_summary(node: Node, source: bytes) -> str | None:
    """Extract the summary text from a JSDoc comment preceding *node*."""
    prev = node.prev_named_sibling
    if prev is None or prev.type != "comment":
        if node.parent is None:
            return None
        idx = node.parent.children.index(node)
        if idx <= 0:
            return None
        prev = node.parent.children[idx - 1]
        if prev.type != "comment":
            return None
    text = node_text(prev, source)
    if not text.startswith("/**"):
        return None
    cleaned = _JSDOC_STAR_RE.sub(" ", text.strip("/* \n")).strip()
    cleaned = _JSDOC_TAG_RE.split(cleaned)[0].strip()
    return cleaned or None


def declaration_signature(node: Node, source: bytes) -> str:
    """Build a compact signature for a declaration node.

    For classes and interfaces, includes member signatures.
    """
    actual = unwrap_export(node)
    decl = node_text(actual, source).split("\n", 1)[0].rstrip(" {")
    if actual.type in ("class_declaration", "interface_declaration"):
        body = actual.child_by_field_name("body")
        if body:
            member_sigs: list[str] = []
            for child in body.children:
                if child.type in (
                    "method_definition",
                    "method_signature",
                    "abstract_method_signature",
                    "public_field_definition",
                    "property_signature",
                ) and child.child_by_field_name("name"):
                    sig = node_text(child, source).split("\n", 1)[0].rstrip(" {;")
                    member_sigs.append(sig)
            if member_sigs:
                return f"{decl}: {'; '.join(member_sigs)}"
    return decl
