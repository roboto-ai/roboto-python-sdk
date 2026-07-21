"""Chunking strategies by file type.

Each chunker returns a list of dicts with keys:
  file_path, chunk_path, content, file_type
"""

from __future__ import annotations

import ast
import configparser
import csv
import io
import json
import re
import tomllib
from pathlib import Path

import yaml

from . import _treesitter as ts_support

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LARGE_CHUNK = 3000
SUB_CHUNK_TARGET = 1500
MIN_CHUNK = 200
_MERGE_META_KEYS = frozenset({"decorators", "directives", "code_languages"})

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_RST_UNDERLINE_HEADING = re.compile(r"^(.+)\n([=\-~^\"'+#])\2{2,}$", re.MULTILINE)
_RST_OVERLINE_HEADING = re.compile(
    r"^([=\-~^\"'+#])\1{2,}\n(.+)\n\1\1{2,}$", re.MULTILINE
)
_RST_DIRECTIVE_RE = re.compile(r"^\.\.\s+([\w-]+)::", re.MULTILINE)
_RST_CODE_BLOCK_RE = re.compile(
    r"^\.\.\s+(?:code-block|sourcecode|highlight)::\s*(\w*)\s*\n((?:[ \t]+\S.*\n?|\s*\n)*)",
    re.MULTILINE,
)
_RST_TOCTREE_RE = re.compile(
    r"^\.\.\s+toctree::\s*\n((?:[ \t]+\S.*\n?|\s*\n)*)", re.MULTILINE
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chunk_label(text: str, fallback_start: int, fallback_end: int) -> str:
    """Derive a semantic label from the first significant line of a chunk."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "!", "[")):
            if len(stripped) > 60:
                return stripped[:57].rsplit(" ", 1)[0] + "..."
            return stripped
    if fallback_start == fallback_end:
        return f"paragraph {fallback_start}"
    return f"paragraph {fallback_start}\u2013{fallback_end}"


def text_chunks(
    content: str, file_path: str, file_type: str, target: int = 1500
) -> list[dict]:
    paragraphs = re.split(r"\n\n+", content)
    chunks: list[dict] = []
    buf: list[str] = []
    buf_len = 0
    start = 1

    for i, para in enumerate(paragraphs, 1):
        buf.append(para)
        buf_len += len(para)
        if buf_len >= target or i == len(paragraphs):
            end = start + len(buf) - 1
            combined = "\n\n".join(buf)
            label = _chunk_label(combined, start, end)
            chunks.append(
                {
                    "file_path": file_path,
                    "chunk_path": label,
                    "content": combined,
                    "file_type": file_type,
                }
            )
            start = end + 1
            buf = []
            buf_len = 0

    return chunks or [
        {
            "file_path": file_path,
            "chunk_path": Path(file_path).stem,
            "content": content,
            "file_type": file_type,
        }
    ]


def _continuation_prefix(file_type: str, decl_line: str) -> str:
    """Return a context-restoring prefix for continuation sub-chunks."""
    if file_type.startswith("code:python"):
        return f"# ... continues: {decl_line}\n\n"
    if file_type.startswith("code:"):
        return f"// ... continues: {decl_line}\n\n"
    if file_type:
        return f"[continues: {decl_line}]\n\n"
    return ""


def _split_score(lines: list[str], index: int, file_type: str) -> float:
    """Score a candidate split point between ``lines[index-1]`` and ``lines[index]``.

    Higher scores indicate better boundaries.  Negative scores (e.g. -1.0 for
    lines inside reST code-block directives) are filtered out by callers that
    check ``score > 0``, preventing splits at those positions.
    """
    if index <= 0 or index >= len(lines):
        return 0.0

    current = lines[index]
    current_stripped = current.rstrip("\n")
    is_blank = not current_stripped.strip()

    # For reST/text: penalise lines inside code-block directives so they
    # stay attached to their context — including blank lines, which can
    # appear between paragraphs inside a directive body.
    if file_type in ("text",) or file_type.startswith("data:"):
        for j in range(index - 1, max(index - 30, -1), -1):
            prev = lines[j].rstrip("\n")
            if not prev.strip():
                continue
            if _RST_DIRECTIVE_RE.match(prev):
                # We are inside a directive's indented body.  Blank lines
                # and indented lines are both protected.
                if is_blank or current_stripped[0] in (" ", "\t"):
                    return -1.0
                break
            if prev and prev[0] not in (" ", "\t"):
                break  # hit a non-indented line — not in a directive

    # Blank line: best natural boundary
    if is_blank:
        return 1.0

    is_code = file_type.startswith("code:")

    if is_code:
        # Indentation drop: current indent < previous non-blank indent
        current_indent = len(current_stripped) - len(current_stripped.lstrip())
        for j in range(index - 1, max(index - 10, -1), -1):
            prev = lines[j].rstrip("\n")
            if prev.strip():
                prev_indent = len(prev) - len(prev.lstrip())
                if current_indent < prev_indent:
                    return 0.7
                break

        # Zero-indent line
        if current_indent == 0 and current_stripped.strip():
            return 0.5

    return 0.0


def _split_large(chunk: dict, target: int = SUB_CHUNK_TARGET) -> list[dict]:
    """Split an oversized chunk, preferring semantic boundaries.

    Scores candidate split points (blank lines, indentation drops, zero-indent
    lines) and picks the best one within each target-sized window.  Parts 2+
    are prefixed with a language-appropriate continuation comment.
    """
    content = chunk["content"]
    lines = content.splitlines(keepends=True)
    file_type = chunk.get("file_type", "")

    # Extract the first non-empty line as a declaration hint for continuations.
    decl_line = ""
    for ln in content.splitlines():
        stripped = ln.strip()
        if stripped:
            decl_line = stripped
            break

    prefix = _continuation_prefix(file_type, decl_line) if decl_line else ""

    parts: list[dict] = []
    buf: list[str] = []
    buf_len = 0
    part_num = 1
    # Track scored candidate split points: (buf_index, score)
    candidates: list[tuple[int, float]] = []
    max_size = target * 2

    for i, line in enumerate(lines):
        buf.append(line)
        buf_len += len(line)

        # Start tracking candidates once past the halfway mark
        if buf_len >= target // 2:
            score = _split_score(lines, i, file_type)
            if score > 0:
                candidates.append((len(buf), score))

        if buf_len >= target:
            # Pick the best candidate; break ties by proximity to target midpoint
            best_idx = None
            if candidates:
                midpoint = len(buf) // 2
                candidates.sort(key=lambda c: (-c[1], abs(c[0] - midpoint)))
                best_idx = candidates[0][0]

            if best_idx is not None:
                emit = buf[:best_idx]
                remaining = buf[best_idx:]
            elif buf_len >= max_size:
                # Force-split: no good candidate and buffer is very large
                emit = buf
                remaining = []
            else:
                # No good candidate yet but below max_size — keep
                # accumulating to find a better split point.
                continue

            part_content = "".join(emit)
            if part_num > 1 and prefix:
                part_content = prefix + part_content

            parts.append(
                {
                    **chunk,
                    "chunk_path": f"{chunk['chunk_path']} (part {part_num})",
                    "content": part_content,
                }
            )
            part_num += 1
            buf = remaining
            buf_len = sum(len(ln) for ln in buf)
            candidates = []

    if buf:
        part_content = "".join(buf)
        if parts:
            if prefix:
                part_content = prefix + part_content
            parts.append(
                {
                    **chunk,
                    "chunk_path": f"{chunk['chunk_path']} (part {part_num})",
                    "content": part_content,
                }
            )
        else:
            parts.append({**chunk, "content": part_content})

    return parts


def merge_small_chunks(
    chunks: list[dict],
    min_size: int = MIN_CHUNK,
    max_merged: int = SUB_CHUNK_TARGET,
) -> list[dict]:
    """Merge adjacent small chunks to improve embedding quality.

    One-liner functions, type aliases, and other tiny symbols are combined
    into larger chunks so embeddings are more meaningful.
    """
    if not chunks:
        return chunks

    def _is_small(c: dict) -> bool:
        return len(c["content"]) < min_size

    def _emit_merged(group: list[dict]) -> dict:
        paths = [c["chunk_path"] for c in group]
        content = "\n\n".join(c["content"] for c in group)
        merged = {
            **group[0],
            "chunk_path": "; ".join(paths),
            "content": content,
            "_merged_paths": ", ".join(paths),
        }
        # Combine metadata keys across merged chunks using set union
        for key in _MERGE_META_KEYS:
            vals = set()
            for c in group:
                if key in c:
                    vals.update(v.strip() for v in c[key].split(","))
            if vals:
                merged[key] = ", ".join(sorted(vals))
        return merged

    result: list[dict] = []
    merge_buf: list[dict] = []
    merge_len = 0

    for chunk in chunks:
        if _is_small(chunk):
            # Check if adding this chunk would exceed max_merged
            new_len = merge_len + len(chunk["content"])
            if merge_buf and new_len > max_merged:
                result.append(_emit_merged(merge_buf))
                merge_buf = []
                merge_len = 0
            merge_buf.append(chunk)
            merge_len += len(chunk["content"])
        else:
            # Large chunk — flush any pending small chunks first
            if merge_buf:
                result.append(_emit_merged(merge_buf))
                merge_buf = []
                merge_len = 0
            result.append(chunk)

    # Trailing small chunks
    if merge_buf:
        if result and _is_small(merge_buf[0]) and len(merge_buf) == 1:
            # Single trailing small chunk: merge into preceding chunk if possible
            prev = result[-1]
            combined_len = len(prev["content"]) + len(merge_buf[0]["content"])
            if combined_len <= max_merged:
                merged = _emit_merged([prev, merge_buf[0]])
                result[-1] = merged
            else:
                result.append(_emit_merged(merge_buf))
        else:
            result.append(_emit_merged(merge_buf))

    return result


def _py_node_label(node: ast.AST) -> str:
    """Derive a short chunk_path label for a top-level AST node."""
    if isinstance(node, ast.AsyncFunctionDef):
        return f"async def {node.name}"
    if isinstance(node, ast.FunctionDef):
        return f"def {node.name}"
    if isinstance(node, ast.ClassDef):
        return f"class {node.name}"
    if isinstance(node, ast.Assign):
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if names:
            return ", ".join(names)
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "imports"
    return ""


def _py_group_label(nodes: list[ast.AST], is_preamble: bool) -> str:
    """Derive a chunk_path label for a group of consecutive AST nodes."""
    if is_preamble:
        return "(preamble)"
    labels = dict.fromkeys(  # preserve order, deduplicate
        label for node in nodes if (label := _py_node_label(node))
    )
    return ", ".join(labels) if labels else "(module-level code)"


# ---------------------------------------------------------------------------
# Chunkers
# ---------------------------------------------------------------------------


def chunk_markdown(content: str, file_path: str) -> list[dict]:
    headings = list(_MD_HEADING.finditer(content))
    if not headings:
        return text_chunks(content, file_path, "markdown")

    chunks: list[dict] = []
    hierarchy: list[str] = []

    for idx, match in enumerate(headings):
        level = len(match.group(1))
        title = match.group(2).strip()
        start = match.start()
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(content)

        while len(hierarchy) >= level:
            hierarchy.pop()
        hierarchy.append(title)

        chunks.append(
            {
                "file_path": file_path,
                "chunk_path": " > ".join(hierarchy),
                "content": content[start:end].strip(),
                "file_type": "markdown",
            }
        )

    preamble = content[: headings[0].start()].strip()
    if preamble:
        chunks.insert(
            0,
            {
                "file_path": file_path,
                "chunk_path": "(preamble)",
                "content": preamble,
                "file_type": "markdown",
            },
        )

    return chunks


def chunk_python(content: str, file_path: str) -> list[dict]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return text_chunks(content, file_path, "code:python")

    chunks: list[dict] = []
    buf: list[ast.AST] = []  # consecutive non-def/class nodes
    seen_def = False

    def _flush_buf() -> None:
        nonlocal buf
        if not buf:
            return
        text = "\n".join(ast.unparse(n) for n in buf)
        chunks.append(
            {
                "file_path": file_path,
                "chunk_path": _py_group_label(buf, not seen_def),
                "content": text,
                "file_type": "code:python",
            }
        )
        buf = []

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            buf.append(node)
            continue

        _flush_buf()
        seen_def = True

        name = _py_node_label(node)
        text = ast.unparse(node)
        chunk = {
            "file_path": file_path,
            "chunk_path": name,
            "content": text,
            "file_type": "code:python",
        }

        # E6: extract decorator names as metadata
        if hasattr(node, "decorator_list") and node.decorator_list:
            chunk["decorators"] = ", ".join(
                ast.unparse(d).split("(")[0] for d in node.decorator_list
            )

        if len(text) > LARGE_CHUNK and isinstance(node, ast.ClassDef):
            method_chunks = _split_class(file_path, node, name)
            if method_chunks:
                chunks.extend(method_chunks)
                continue
            chunks.extend(_split_large(chunk))
            continue
        elif len(text) > LARGE_CHUNK:
            chunks.extend(_split_large(chunk))
            continue

        chunks.append(chunk)

    _flush_buf()

    chunks = chunks or text_chunks(content, file_path, "code:python")
    return merge_small_chunks(chunks)


def _split_class(
    file_path: str,
    node: ast.ClassDef,
    name: str,
) -> list[dict] | None:
    """Split a large class into preamble + per-method chunks.

    Returns ``None`` if the class has no methods (caller should fall back to
    ``_split_large``).
    """
    methods = [
        child
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not methods:
        return None

    non_methods = [child for child in node.body if child not in methods]
    chunks: list[dict] = []

    # Preamble: class declaration + non-method body (fields, docstring, etc.)
    if non_methods:
        # Rebuild a stub class with only the non-method members
        stub = ast.ClassDef(
            name=node.name,
            bases=node.bases,
            keywords=node.keywords,
            body=non_methods,
            decorator_list=node.decorator_list,
            type_params=getattr(node, "type_params", []),
        )
        chunks.append(
            {
                "file_path": file_path,
                "chunk_path": f"{name} > (preamble)",
                "content": ast.unparse(stub),
                "file_type": "code:python",
            }
        )

    for method in methods:
        method_chunk = {
            "file_path": file_path,
            "chunk_path": f"{name} > {_py_node_label(method)}",
            "content": ast.unparse(method),
            "file_type": "code:python",
        }
        if hasattr(method, "decorator_list") and method.decorator_list:
            method_chunk["decorators"] = ", ".join(
                ast.unparse(d).split("(")[0] for d in method.decorator_list
            )
        chunks.append(method_chunk)

    return chunks


def chunk_ts_js(content: str, file_path: str) -> list[dict]:
    tree = ts_support.parse(content, Path(file_path))
    if tree is None:
        return text_chunks(content, file_path, "code:typescript")

    source = content.encode()

    def _node_text(node) -> str:
        return ts_support.node_text(node, source)

    def _is_jsdoc(node) -> bool:
        return (
            node.type == "comment"
            and source[node.start_byte : node.start_byte + 3] == b"/**"
        )

    def _chunk_path_for(node, exported: bool = False) -> str:
        prefix = "export " if exported else ""
        name = ts_support.symbol_name(node, source)
        node_type = node.type
        if node_type == "function_declaration":
            return f"{prefix}function {name}"
        if node_type == "class_declaration":
            return f"{prefix}class {name}"
        if node_type == "interface_declaration":
            return f"{prefix}interface {name}"
        if node_type == "type_alias_declaration":
            return f"{prefix}type {name}"
        if node_type == "enum_declaration":
            return f"{prefix}enum {name}"
        if node_type == "lexical_declaration":
            kind = "const"
            for child in node.children:
                if child.type in ("const", "let", "var"):
                    kind = child.type
                    break
            return f"{prefix}{kind} {name}"
        return f"{prefix}{name or node_type}"

    def _is_declaration(node) -> bool:
        actual = ts_support.unwrap_export(node)
        return actual.type in ts_support.RANKED_TYPES

    chunks: list[dict] = []
    buf: list = []  # non-declaration root children
    seen_decl = False

    def _flush_buf() -> None:
        nonlocal buf
        if not buf:
            return
        text = "\n".join(_node_text(n) for n in buf).strip()
        if text:
            chunks.append(
                {
                    "file_path": file_path,
                    "chunk_path": "(preamble)"
                    if not seen_decl
                    else "(module-level code)",
                    "content": text,
                    "file_type": "code:typescript",
                }
            )
        buf = []

    root_children = tree.root_node.children
    i = 0
    while i < len(root_children):
        node = root_children[i]

        if not _is_declaration(node):
            # Accumulate non-declaration nodes (imports, comments, expressions)
            # — but a JSDoc comment right before a declaration belongs with it
            if (
                _is_jsdoc(node)
                and i + 1 < len(root_children)
                and _is_declaration(root_children[i + 1])
            ):
                # Don't buffer this JSDoc; handle it with the next declaration
                _flush_buf()
                jsdoc_node = node
                i += 1
                node = root_children[i]
                # Fall through to declaration handling with jsdoc_node set
            else:
                buf.append(node)
                i += 1
                continue
        else:
            _flush_buf()
            jsdoc_node = None

        seen_decl = True
        actual_node = ts_support.unwrap_export(node)
        exported = actual_node is not node

        # Build chunk text, prepending JSDoc if present
        text = (
            _node_text(jsdoc_node) + "\n" + _node_text(node)
            if jsdoc_node
            else _node_text(node)
        )
        chunk_path = _chunk_path_for(actual_node, exported)
        chunk = {
            "file_path": file_path,
            "chunk_path": chunk_path,
            "content": text,
            "file_type": "code:typescript",
        }

        if len(text) > LARGE_CHUNK and actual_node.type == "class_declaration":
            split = _split_ts_class(
                file_path, actual_node, chunk_path, source, jsdoc_node
            )
            if split:
                chunks.extend(split)
                i += 1
                continue
            chunks.extend(_split_large(chunk))
            i += 1
            continue
        elif len(text) > LARGE_CHUNK:
            chunks.extend(_split_large(chunk))
            i += 1
            continue

        chunks.append(chunk)
        i += 1

    _flush_buf()

    chunks = chunks or text_chunks(content, file_path, "code:typescript")
    return merge_small_chunks(chunks)


def _split_ts_class(
    file_path: str,
    node,
    chunk_path: str,
    source: bytes,
    jsdoc_node=None,
) -> list[dict] | None:
    """Split a large TS/JS class into preamble + per-member chunks.

    Returns ``None`` if the class has no members (caller should fall back
    to ``_split_large``).
    """
    body = node.child_by_field_name("body")
    if not body:
        return None

    members = [
        child
        for child in body.children
        if child.type in ("method_definition", "public_field_definition")
    ]
    if not members:
        return None

    chunks: list[dict] = []

    # Preamble: JSDoc + class declaration through first member
    preamble_end = members[0].start_byte
    preamble_text = source[node.start_byte : preamble_end].decode().strip()
    if jsdoc_node:
        preamble_text = ts_support.node_text(jsdoc_node, source) + "\n" + preamble_text
    if preamble_text:
        chunks.append(
            {
                "file_path": file_path,
                "chunk_path": f"{chunk_path} > (preamble)",
                "content": preamble_text,
                "file_type": "code:typescript",
            }
        )

    for member in members:
        chunks.append(
            {
                "file_path": file_path,
                "chunk_path": f"{chunk_path} > {ts_support.symbol_name(member, source)}",
                "content": ts_support.node_text(member, source),
                "file_type": "code:typescript",
            }
        )

    return chunks


def chunk_json(content: str, file_path: str) -> list[dict]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return text_chunks(content, file_path, "data:json")

    if isinstance(data, list) and data:
        if isinstance(data[0], dict):
            id_keys = ("id", "name", "title", "key", "slug")
            chunks: list[dict] = []
            for i, element in enumerate(data):
                label = f"[{i}]"
                for k in id_keys:
                    if k in element:
                        label = f'[{i}] {k}="{element[k]}"'
                        break
                chunks.append(
                    {
                        "file_path": file_path,
                        "chunk_path": label,
                        "content": json.dumps(element, indent=2),
                        "file_type": "data:json",
                    }
                )
            return chunks

        # Array of non-objects — group into size-bounded chunks
        chunks = []
        buf: list = []
        buf_len = 0
        start_idx = 0
        for i, element in enumerate(data):
            buf.append(element)
            buf_len += len(json.dumps(element))
            if buf_len >= 2000 or i == len(data) - 1:
                end_idx = i
                label = (
                    f"[{start_idx}]"
                    if start_idx == end_idx
                    else f"[{start_idx}]\u2013[{end_idx}]"
                )
                chunks.append(
                    {
                        "file_path": file_path,
                        "chunk_path": label,
                        "content": json.dumps(buf, indent=2),
                        "file_type": "data:json",
                    }
                )
                start_idx = i + 1
                buf = []
                buf_len = 0
        return chunks

    if isinstance(data, dict):
        chunks = []
        for key, value in data.items():
            serialized = json.dumps({key: value}, indent=2)
            if len(serialized) > LARGE_CHUNK and isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    chunks.append(
                        {
                            "file_path": file_path,
                            "chunk_path": f"{key} > {sub_key}",
                            "content": json.dumps({sub_key: sub_value}, indent=2),
                            "file_type": "data:json",
                        }
                    )
            else:
                chunks.append(
                    {
                        "file_path": file_path,
                        "chunk_path": key,
                        "content": serialized,
                        "file_type": "data:json",
                    }
                )
        return chunks

    return [
        {
            "file_path": file_path,
            "chunk_path": Path(file_path).stem,
            "content": content,
            "file_type": "data:json",
        }
    ]


def _csv_line(fields: list[str]) -> str:
    """Format *fields* as a properly quoted CSV line."""
    buf = io.StringIO()
    csv.writer(buf).writerow(fields)
    return buf.getvalue().rstrip("\r\n")


def chunk_csv(content: str, file_path: str) -> list[dict]:
    try:
        reader = csv.DictReader(io.StringIO(content))
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    except Exception:
        return text_chunks(content, file_path, "data:csv")

    if not rows:
        return text_chunks(content, file_path, "data:csv")

    header_line = _csv_line(fieldnames)
    id_col = None
    for candidate in ("id", "name", "key", "title"):
        if candidate in fieldnames:
            id_col = candidate
            break
    if id_col is None and fieldnames:
        id_col = fieldnames[0]

    chunks: list[dict] = []
    group: list[str] = []
    group_len = 0
    group_start = 1

    for i, row in enumerate(rows):
        line = _csv_line([str(row.get(f, "")) for f in fieldnames])
        group.append(line)
        group_len += len(line)

        if group_len >= 2000 or i == len(rows) - 1:
            end = group_start + len(group) - 1
            cp = f"rows {group_start}\u2013{end}"
            if id_col:
                first_id = rows[group_start - 1].get(id_col, "")
                last_id = rows[end - 1].get(id_col, "")
                cp += f" ({id_col}: {first_id}\u2013{last_id})"

            chunks.append(
                {
                    "file_path": file_path,
                    "chunk_path": cp,
                    "content": header_line + "\n" + "\n".join(group),
                    "file_type": "data:csv",
                }
            )
            group_start = end + 1
            group = []
            group_len = 0

    return chunks


def chunk_config(content: str, file_path: str) -> list[dict]:
    ext = Path(file_path).suffix
    data = None

    if ext in (".yaml", ".yml"):
        try:
            data = yaml.safe_load(content)
        except Exception:
            pass
    elif ext == ".toml":
        try:
            data = tomllib.loads(content)
        except Exception:
            pass
    elif ext in (".ini", ".cfg"):
        try:
            parser = configparser.ConfigParser()
            parser.read_string(content)
            data = {}
            defaults = dict(parser.defaults())
            if defaults:
                data["DEFAULT"] = defaults
            for section in parser.sections():
                # Exclude inherited defaults to avoid duplicating DEFAULT keys
                section_items = {
                    k: v for k, v in parser.items(section) if k not in defaults
                }
                data[section] = section_items
        except Exception:
            pass

    if isinstance(data, dict) and data:
        return [
            {
                "file_path": file_path,
                "chunk_path": key,
                "content": json.dumps({key: value}, indent=2),
                "file_type": "data:config",
            }
            for key, value in data.items()
        ]

    return text_chunks(content, file_path, "data:config")


def _extract_rst_directives(content: str) -> dict[str, str]:
    """Extract reST directive types and code-block languages from content."""
    directives = list(
        dict.fromkeys(m.group(1) for m in _RST_DIRECTIVE_RE.finditer(content))
    )
    result: dict[str, str] = {}
    if directives:
        result["directives"] = ", ".join(directives)

    code_langs: list[str] = []
    for m in _RST_CODE_BLOCK_RE.finditer(content):
        lang = m.group(1).strip()
        if lang and lang not in code_langs:
            code_langs.append(lang)
    if code_langs:
        result["code_languages"] = ", ".join(code_langs)

    # Extract toctree entries as links
    toctree_links: list[str] = []
    for m in _RST_TOCTREE_RE.finditer(content):
        for line in m.group(1).splitlines():
            entry = line.strip()
            if entry and not entry.startswith(":"):
                toctree_links.append(entry)
    if toctree_links:
        result["links"] = ", ".join(dict.fromkeys(toctree_links))

    return result


def chunk_rst(content: str, file_path: str) -> list[dict]:
    # Collect both underline-only and overline+underline headings.
    # Overline headings use a (char, True) key; underline-only use (char, False).
    raw: list[tuple[int, str, str, bool]] = []  # (start, title, char, has_overline)

    for m in _RST_UNDERLINE_HEADING.finditer(content):
        raw.append((m.start(), m.group(1).strip(), m.group(2), False))
    for m in _RST_OVERLINE_HEADING.finditer(content):
        raw.append((m.start(), m.group(2).strip(), m.group(1), True))

    if not raw:
        return text_chunks(content, file_path, "text")

    raw.sort(key=lambda x: x[0])

    # Determine heading levels by (char, has_overline) order of appearance.
    # Overline+underline headings are conventionally higher-level than
    # underline-only headings using the same character.
    level_keys: list[tuple[str, bool]] = []
    for _, _, char, has_overline in raw:
        key = (char, has_overline)
        if key not in level_keys:
            level_keys.append(key)

    chunks: list[dict] = []
    hierarchy: list[str] = []

    for idx, (start, title, char, has_overline) in enumerate(raw):
        level = level_keys.index((char, has_overline)) + 1
        end = raw[idx + 1][0] if idx + 1 < len(raw) else len(content)

        while len(hierarchy) >= level:
            hierarchy.pop()
        hierarchy.append(title)

        chunk_content = content[start:end].strip()
        chunk_dict = {
            "file_path": file_path,
            "chunk_path": " > ".join(hierarchy),
            "content": chunk_content,
            "file_type": "text",
        }
        chunk_dict.update(_extract_rst_directives(chunk_content))
        chunks.append(chunk_dict)

    preamble = content[: raw[0][0]].strip()
    if preamble:
        preamble_chunk = {
            "file_path": file_path,
            "chunk_path": "(preamble)",
            "content": preamble,
            "file_type": "text",
        }
        preamble_chunk.update(_extract_rst_directives(preamble))
        chunks.insert(0, preamble_chunk)

    return chunks
