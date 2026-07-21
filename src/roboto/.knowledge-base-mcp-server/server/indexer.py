"""File discovery, chunking dispatch, and incremental reindexing."""

from __future__ import annotations

import ast
import csv
import io
import json
import re
import sys
import time
from pathlib import Path

from typing import Any

import yaml

from . import chunkers

# ---------------------------------------------------------------------------
# Regex for extracting file descriptions
# ---------------------------------------------------------------------------

_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
_MD_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_JSDOC_FILE_RE = re.compile(
    r"/\*\*\s*\n\s*\*?\s*@(?:fileoverview|file|module|packageDocumentation)\s+(.*?)(?:\n\s*\*?\s*@|\*/)",
    re.DOTALL,
)
_JSDOC_BLOCK_RE = re.compile(r"\A\s*/\*\*(.*?)\*/", re.DOTALL)
_MD_LINK_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^)]+)\)")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EXTRA_CHUNK_KEYS = frozenset({
    "decorators", "directives", "code_languages",
    "links", "_merged_paths",
})

_COMMENT_SKIP_MARKERS = ("copyright", "license", "spdx", "pylint", "noqa", "type:")

FILE_TYPES: dict[str, str] = {
    ".md": "markdown",
    ".mdx": "markdown",
    ".py": "code:python",
    ".ts": "code:typescript",
    ".tsx": "code:typescript",
    ".js": "code:typescript",
    ".jsx": "code:typescript",
    ".txt": "text",
    ".rst": "text",
    ".adoc": "text",
    ".tex": "text",
    ".org": "text",
    ".json": "data:json",
    ".csv": "data:csv",
    ".yaml": "data:config",
    ".yml": "data:config",
    ".toml": "data:config",
    ".ini": "data:config",
    ".cfg": "data:config",
}

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".knowledge-base-mcp-server",
    "__pycache__",
    ".tox",
    "dist",
    "build",
    ".venv",
    "venv",
    ".env",
}

MAX_FILE_SIZE = 1_000_000
MAX_LINE_LENGTH = 10_000
SCAN_DEBOUNCE_SECS = 300

_CHUNKER = {
    "markdown": chunkers.chunk_markdown,
    "code:python": chunkers.chunk_python,
    "code:typescript": chunkers.chunk_ts_js,
    "data:json": chunkers.chunk_json,
    "data:csv": chunkers.chunk_csv,
    "data:config": chunkers.chunk_config,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_for_match(name: str) -> str:
    """Lowercase and strip separators so different casing/delimiter styles compare equal.

    ``ConnectionPool``, ``connection_pool``, ``connection-pool``, and
    ``connectionPool`` all normalize to ``connectionpool``.
    """
    return name.lower().replace("_", "").replace("-", "")


def _bare_stem(path: Path) -> str:
    """Return the filename with all extensions removed.

    ``Path("api-client.test.ts")`` -> ``"api-client"``,
    ``Path("types.d.ts")`` -> ``"types"``,
    ``Path(".env.local")`` -> ``".env"``.
    """
    return path.name.removesuffix("".join(path.suffixes))


def _py_symbol_rank(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    file_stem: str = "",
) -> tuple[bool, bool, bool]:
    """Sort key: filename match first, then classes before functions, public before private.

    A symbol whose name matches the file stem (case-insensitive, separators
    stripped) ranks highest, e.g. ``ConnectionPool`` in
    ``connection_pool.py``.
    """
    norm_name = _normalize_for_match(node.name)
    norm_stem = _normalize_for_match(file_stem)
    name_matches_file = norm_stem != "" and norm_name == norm_stem
    is_func = not isinstance(node, ast.ClassDef)
    is_private = node.name.startswith("_")
    return (not name_matches_file, is_func, is_private)


def _py_func_sig(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    strip_self: bool = False,
) -> str:
    """Return a compact one-line signature for a function or method node."""
    args_node = node.args
    if strip_self and args_node.args and args_node.args[0].arg in ("self", "cls"):
        args_node = ast.arguments(
            posonlyargs=args_node.posonlyargs,
            args=args_node.args[1:],
            vararg=args_node.vararg,
            kwonlyargs=args_node.kwonlyargs,
            kw_defaults=args_node.kw_defaults,
            kwarg=args_node.kwarg,
            defaults=args_node.defaults,
        )
    args = ast.unparse(args_node)
    sig = f"{node.name}({args})"
    if node.returns:
        sig += f" -> {ast.unparse(node.returns)}"
    return sig


def py_signature(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
) -> str:
    """Return a compact signature reconstructed from an AST node.

    Functions produce ``def name(args) -> ret``.
    Classes produce the declaration followed by public method signatures.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
        return prefix + _py_func_sig(node)

    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        decl = f"class {node.name}({bases})" if bases else f"class {node.name}"
        methods = [
            _py_func_sig(child, strip_self=True)
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not child.name.startswith("_")
        ]
        if methods:
            return f"{decl}: {'; '.join(methods)}"
        return decl

    return node.name if hasattr(node, "name") else ""


def _ts_symbol_description(content: str, path: Path) -> str | None:
    """Extract a description from the highest-ranked top-level TS/JS symbol.

    Prefers classes and interfaces over functions. Returns the JSDoc summary
    attached to the chosen symbol, or its signature if no JSDoc is present.
    """
    from . import _treesitter as ts_support

    tree = ts_support.parse(content, path)
    if tree is None:
        return None

    source = content.encode()

    # Collect top-level declarations
    candidates: list[tuple[int, Any]] = []
    for node in tree.root_node.children:
        actual = ts_support.unwrap_export(node)
        if actual is node and node.type == "export_statement":
            continue
        if actual.type in ts_support.RANKED_TYPES:
            candidates.append((ts_support.RANKED_TYPES[actual.type], node))

    if not candidates:
        return None

    # Sort by filename match first (False < True, so invert), then type rank
    norm_stem = _normalize_for_match(_bare_stem(path))
    candidates.sort(
        key=lambda x: (
            _normalize_for_match(ts_support.symbol_name(x[1], source)) != norm_stem,
            x[0],
        )
    )

    for _, node in candidates:
        name = ts_support.symbol_name(node, source)
        summary = ts_support.jsdoc_summary(node, source)
        if summary:
            return f"{name} — {summary}" if name else summary

    # No JSDoc found; list symbol signatures instead
    sigs = [
        s
        for _, nd in candidates[:4]
        if (s := ts_support.declaration_signature(nd, source))
    ]
    if sigs:
        suffix = f" (+{len(candidates) - 4} more)" if len(candidates) > 4 else ""
        return "; ".join(sigs) + suffix

    return None


def _is_binary(path: Path) -> bool:
    try:
        return b"\x00" in path.read_bytes()[:8192]
    except OSError:
        return True


def _has_long_lines(path: Path) -> bool:
    try:
        with path.open(errors="replace") as f:
            return any(len(line) > MAX_LINE_LENGTH for line in f)
    except OSError:
        return True


def _file_description(path: Path, file_type: str, content: str | None = None) -> str:
    """Extract a human-readable description from a file.

    Tries, in order: explicit metadata, structural elements (headings,
    docstrings, JSDoc), signature listings, and the filename as a last
    resort. Pass *content* to avoid re-reading the file.
    """
    if content is None:
        try:
            content = path.read_text(errors="replace")
        except OSError:
            return ""

    if not content.strip():
        return ""

    # -- Markdown: frontmatter description, then table of contents --
    if file_type == "markdown":
        fm = _FRONT_MATTER_RE.match(content)
        if fm:
            for field in ("description", "summary", "excerpt"):
                for line in fm.group(1).splitlines():
                    if line.strip().lower().startswith(f"{field}:"):
                        val = line.split(":", 1)[1].strip().strip("\"'")
                        if val:
                            return val
        # Build a table of contents from H1/H2/H3 headings, stripping
        # fenced code blocks first to avoid false matches.
        prose = _FENCED_CODE_RE.sub("", content)
        headings: list[str] = []
        for m in re.finditer(r"^(#{1,3})\s+(.+)$", prose, re.MULTILINE):
            headings.append(m.group(2).strip())
        if headings:
            return " > ".join(headings)
        return path.stem

    # -- Python: module docstring, then top-level symbol docstrings,
    #    then first comment block, then filename --
    if file_type == "code:python":
        try:
            tree = ast.parse(content)
            docstring = ast.get_docstring(tree)
            if docstring:
                # PEP 257: first paragraph is the summary
                first_para = docstring.split("\n\n")[0]
                return first_para.replace("\n", " ")
            # No module docstring; prefer primary class docstrings
            # over helper functions via _py_symbol_rank.
            top_level = [
                node
                for node in ast.iter_child_nodes(tree)
                if isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
            ]
            if top_level:
                stem = _bare_stem(path)
                ranked = sorted(top_level, key=lambda n: _py_symbol_rank(n, stem))
                for node in ranked:
                    ds = ast.get_docstring(node)
                    if ds:
                        first_para = ds.split("\n\n")[0].replace("\n", " ")
                        return f"{node.name} — {first_para}"
                # No docstrings; summarize by listing signatures
                sigs = [py_signature(n) for n in ranked[:4]]
                suffix = f" (+{len(top_level) - 4} more)" if len(top_level) > 4 else ""
                return "; ".join(sigs) + suffix
        except SyntaxError:
            pass
        # Fallback: first comment block, skipping license/encoding headers.
        # Discard a contiguous block if any line contains a skip marker.
        block: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#!") or "coding" in stripped:
                continue
            if stripped.startswith("#"):
                text = stripped.lstrip("# ").strip()
                if text:
                    block.append(text)
                continue
            # End of comment block; check for license header
            if block:
                block_text = " ".join(block).lower()
                if not any(w in block_text for w in _COMMENT_SKIP_MARKERS):
                    return block[0]
                block = []
            if stripped:
                break
        # Handle trailing comment block (file contains only comments)
        if block:
            block_text = " ".join(block).lower()
            if not any(w in block_text for w in _COMMENT_SKIP_MARKERS):
                return block[0]
        return path.stem.replace("_", " ")

    # -- TypeScript/JavaScript: JSDoc @fileoverview/@module, then symbol JSDoc --
    if file_type == "code:typescript":
        m = _JSDOC_FILE_RE.search(content[:2000])
        if m:
            desc = re.sub(r"\s*\*\s*", " ", m.group(1)).strip()
            return desc
        # Leading JSDoc block without explicit tag
        m = _JSDOC_BLOCK_RE.match(content)
        if m:
            text = re.sub(r"\s*\*\s*", " ", m.group(1)).strip()
            text = re.split(r"\s@", text)[0].strip()
            if text:
                return text
        # No file-level JSDoc; fall back to tree-sitter symbol extraction.
        desc = _ts_symbol_description(content, path)
        if desc:
            return desc
        return path.stem.replace("_", " ").replace("-", " ")

    # -- Data files: describe shape --
    if file_type == "data:json":
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return f"JSON array with {len(data)} elements"
            if isinstance(data, dict):
                keys = list(data.keys())[:6]
                suffix = ", \u2026" if len(data) > 6 else ""
                return f"JSON object ({len(data)} keys: {', '.join(keys)}{suffix})"
        except json.JSONDecodeError:
            pass
        return path.name

    if file_type == "data:csv":
        try:
            reader = csv.DictReader(io.StringIO(content))
            cols = reader.fieldnames or []
            row_count = sum(1 for _ in reader)
            return f"{row_count} rows \u00d7 {len(cols)} columns: {', '.join(cols[:6])}"
        except Exception:
            pass
        return path.name

    if file_type == "data:config":
        # YAML/TOML: list top-level keys
        keys: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if (
                stripped
                and not stripped.startswith("#")
                and not stripped.startswith("-")
            ):
                key = stripped.split(":")[0].split("=")[0].strip().strip("[].\"'")
                if key and key not in keys:
                    keys.append(key)
            if len(keys) >= 6:
                break
        if keys:
            return f"Config sections: {', '.join(keys)}"
        return path.name

    # -- Fallback: first non-empty, non-heading line --
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return path.stem


def _document_title(path: Path, file_type: str, content: str | None = None) -> str:
    """Extract a short title from a file for use as chunk metadata.

    Pass *content* to avoid re-reading the file.
    """
    if content is not None:
        head = content[:2048]
    else:
        try:
            with path.open(errors="replace") as f:
                head = f.read(2048)
        except OSError:
            return path.stem

    if file_type == "markdown":
        # Frontmatter title, then first H1
        fm = _FRONT_MATTER_RE.match(head)
        if fm:
            for line in fm.group(1).splitlines():
                if line.strip().lower().startswith("title:"):
                    return line.split(":", 1)[1].strip().strip("\"'")
        m = _MD_TITLE_RE.search(head)
        if m:
            return m.group(1).strip()

    if file_type == "code:python":
        try:
            tree = ast.parse(head)
            docstring = ast.get_docstring(tree)
            if docstring:
                return docstring.split("\n")[0]
            # Fall back to the first top-level class/function
            for node in ast.iter_child_nodes(tree):
                if isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    ds = ast.get_docstring(node)
                    if ds:
                        first_line = ds.split("\n")[0]
                        return f"{node.name} — {first_line}"
                    return py_signature(node)
        except SyntaxError:
            pass

    if file_type == "code:typescript":
        m = _JSDOC_FILE_RE.search(head)
        if m:
            return re.sub(r"\s*\*\s*", " ", m.group(1)).strip()
        # Leading JSDoc block without explicit tag
        m = _JSDOC_BLOCK_RE.match(head)
        if m:
            text = re.sub(r"\s*\*\s*", " ", m.group(1)).strip()
            text = re.split(r"\s@", text)[0].strip()
            if text:
                return text
        # tree-sitter needs the full file, not the 2 KB head.
        if content is None:
            try:
                content = path.read_text(errors="replace")
            except OSError:
                content = head
        desc = _ts_symbol_description(content, path)
        if desc:
            return desc

    return path.stem.replace("_", " ").replace("-", " ")


# ---------------------------------------------------------------------------
# Markdown frontmatter & link extraction (E3)
# ---------------------------------------------------------------------------

def _extract_frontmatter_meta(content: str) -> dict[str, str]:
    """Parse YAML frontmatter and extract ``tags`` and ``category`` as metadata."""
    fm = _FRONT_MATTER_RE.match(content)
    if not fm:
        return {}
    try:
        data = yaml.safe_load(fm.group(1))
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}

    result: dict[str, str] = {}
    tags = data.get("tags")
    if isinstance(tags, list):
        result["tags"] = ", ".join(str(t) for t in tags if t)
    elif isinstance(tags, str) and tags:
        result["tags"] = tags

    category = data.get("category")
    if isinstance(category, str) and category:
        result["category"] = category

    return result


def _extract_internal_links(content: str) -> str:
    """Extract internal (non-HTTP, non-anchor-only) markdown links."""
    cleaned = _FENCED_CODE_RE.sub("", content)
    seen: list[str] = []
    for _, href in _MD_LINK_RE.findall(cleaned):
        if href.startswith(("http://", "https://", "#")):
            continue
        # Strip anchors
        target = href.split("#")[0]
        if target and target not in seen:
            seen.append(target)
    return ", ".join(seen) if seen else ""


# ---------------------------------------------------------------------------
# Snippet extraction (used by both indexer and tools)
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)
_FENCED_CODE_RE = re.compile(r"^```[^\n]*\n.*?^```", re.MULTILINE | re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

# Sentence boundary: punctuation followed by whitespace and an uppercase letter,
# skipping common abbreviations. Chained fixed-width lookbehinds avoid the
# variable-width alternation that Python's ``re`` module rejects.
_ABBREVS = (
    "Dr",
    "Mr",
    "Mrs",
    "Ms",
    "Prof",
    "Sr",
    "Jr",
    "vs",
    "etc",
    "e.g",
    "i.e",
    "Fig",
    "Eq",
    "No",
    "Vol",
)
_ABBREV_LOOKBEHINDS = "".join(rf"(?<!{re.escape(a)})" for a in _ABBREVS)
_SENT_BOUNDARY_RE = re.compile(rf"{_ABBREV_LOOKBEHINDS}[.!?]\s+(?=[A-Z])")


def _first_sentence(text: str, limit: int = 300) -> str:
    """Return the first sentence from prose text.

    Strips frontmatter, code fences, and headings, then returns the first
    sentence of the first non-empty, non-image paragraph.
    """
    cleaned = _FRONT_MATTER_RE.sub("", text)
    cleaned = _FENCED_CODE_RE.sub("", cleaned)
    cleaned = _HEADING_RE.sub("", cleaned)

    for para in re.split(r"\n\n+", cleaned):
        para = para.strip()
        if not para:
            continue
        if para.startswith("![") or para.startswith("[!["):
            continue
        # Replace inline code with placeholders to avoid false sentence breaks
        safe = _INLINE_CODE_RE.sub(lambda m: "\x00" * len(m.group()), para)
        match = _SENT_BOUNDARY_RE.search(safe)
        if match:
            return para[: match.start() + 1].strip()
        return para[:limit].rstrip()

    return text[:limit].strip()


def _code_summary(content: str, file_type: str) -> str:
    """Extract a docstring summary or interface signature from a code chunk.

    Falls back to the first line of the content for unrecognized languages.
    """
    if file_type == "code:python":
        try:
            tree = ast.parse(content)
            for node in ast.iter_child_nodes(tree):
                if isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    ds = ast.get_docstring(node)
                    if ds:
                        first_para = ds.split("\n\n")[0].replace("\n", " ")
                        return first_para
                    return py_signature(node)
            ds = ast.get_docstring(tree)
            if ds:
                return ds.split("\n\n")[0].replace("\n", " ")
        except SyntaxError:
            pass

    if file_type == "code:typescript":
        summary = _ts_code_summary(content)
        if summary:
            return summary

    lines = content.split("\n")
    return lines[0].strip() if lines else ""


def _ts_code_summary(content: str) -> str | None:
    """Extract a JSDoc summary or interface signature from a TS/JS chunk."""
    from . import _treesitter as ts_support

    # Try TypeScript first (covers most JS), then fall back to
    # the JavaScript grammar for JS-only syntax.
    tree = ts_support.parse_language(content, "typescript")
    if tree is None:
        tree = ts_support.parse_language(content, "javascript")
    if tree is None:
        return None

    source = content.encode()

    for node in tree.root_node.children:
        actual = ts_support.unwrap_export(node)
        if actual.type not in ts_support.RANKED_TYPES:
            continue
        name = ts_support.symbol_name(node, source)
        jsdoc = ts_support.jsdoc_summary(node, source)
        if jsdoc:
            return f"{name} — {jsdoc}" if name else jsdoc
        return ts_support.declaration_signature(node, source)

    return None


def _data_summary(content: str, file_type: str, chunk_path: str) -> str:
    """Describe the shape of a data chunk."""
    if file_type == "data:json":
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return f"JSON array ({len(data)} elements)"
            if isinstance(data, dict):
                keys = list(data.keys())[:5]
                suffix = ", \u2026" if len(data) > 5 else ""
                return f"JSON object with keys: {', '.join(keys)}{suffix}"
        except (json.JSONDecodeError, ValueError):
            pass
        return chunk_path

    if file_type == "data:csv":
        try:
            reader = csv.reader(io.StringIO(content))
            header = next(reader)
            row_count = sum(1 for _ in reader)
            return f"{row_count} rows \u00d7 {len(header)} columns: {', '.join(header)}"
        except (StopIteration, csv.Error):
            return chunk_path

    if file_type == "data:config":
        keys: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if (
                stripped
                and not stripped.startswith("#")
                and not stripped.startswith("-")
            ):
                key = stripped.split(":")[0].split("=")[0].strip().strip("[].\"'")
                if key and key not in keys:
                    keys.append(key)
            if len(keys) >= 5:
                break
        if keys:
            return f"Config keys: {', '.join(keys)}"

    return chunk_path


def chunk_snippet(content: str, file_type: str, chunk_path: str) -> str:
    """Return a type-aware one-line summary of a chunk's content."""
    if file_type in ("markdown", "text"):
        return _first_sentence(content)
    if file_type.startswith("code:"):
        return _code_summary(content, file_type)
    if file_type.startswith("data:"):
        return _data_summary(content, file_type, chunk_path)
    return _first_sentence(content)


class Indexer:
    def __init__(
        self,
        collection,
        docs_root: Path,
        kb_dir: Path,
        embedding_fn=None,
    ) -> None:
        self.collection = collection
        self.docs_root = docs_root
        self.kb_dir = kb_dir
        self.meta_path = kb_dir / "file_meta.json"
        self._last_scan: float = 0.0
        if embedding_fn is None:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            embedding_fn = DefaultEmbeddingFunction()
        self._embedding_fn = embedding_fn

    def chunk_file(self, path: Path, content: str | None = None) -> list[dict]:
        rel = str(path.relative_to(self.docs_root))
        file_type = FILE_TYPES.get(path.suffix, "text")

        if content is None:
            try:
                content = path.read_text(errors="replace")
            except OSError as e:
                print(f"Skipping {rel}: {e}", file=sys.stderr)
                return []

        if not content.strip():
            return []

        if file_type == "text" and path.suffix == ".rst":
            try:
                return chunkers.chunk_rst(content, rel)
            except Exception as e:
                print(f"RST chunking failed for {rel}: {e}", file=sys.stderr)

        chunker = _CHUNKER.get(file_type)
        if chunker:
            try:
                return chunker(content, rel)
            except Exception as e:
                print(
                    f"Chunking failed for {rel}, falling back to text: {e}",
                    file=sys.stderr,
                )

        return chunkers.text_chunks(content, rel, file_type)

    def discover_files(self) -> list[Path]:
        files: list[Path] = []
        for p in self.docs_root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in SKIP_DIRS for part in p.relative_to(self.docs_root).parts):
                continue
            if p.suffix not in FILE_TYPES:
                continue
            try:
                stat = p.stat()
            except OSError:
                continue
            if stat.st_size == 0 or stat.st_size > MAX_FILE_SIZE:
                continue
            if _is_binary(p):
                continue
            if _has_long_lines(p):
                continue
            files.append(p)
        return files

    def load_meta(self) -> dict:
        if self.meta_path.exists():
            try:
                return json.loads(self.meta_path.read_text())
            except Exception:
                pass
        return {}

    def _embedding_model_name(self) -> str:
        """Return a stable identifier for the current embedding function."""
        fn = self._embedding_fn
        # SentenceTransformerEmbeddingFunction exposes model_name as a
        # public or private attribute depending on the chromadb version.
        for attr in ("model_name", "_model_name", "_model"):
            val = getattr(fn, attr, None)
            if isinstance(val, str):
                return val
        return type(fn).__qualname__

    def _check_embedding_model(self, meta: dict) -> dict:
        """Clear the collection and metadata if the embedding model has changed."""
        current = self._embedding_model_name()
        stored = meta.get("__embedding_model__")
        if stored is not None and stored != current:
            print(
                f"Embedding model changed ({stored} -> {current}), rebuilding index.",
                file=sys.stderr,
            )
            # Wipe all documents in batches of 5 000 to avoid loading
            # the entire ID list into a single delete call.
            try:
                while True:
                    batch = self.collection.get(limit=5000)["ids"]
                    if not batch:
                        break
                    self.collection.delete(ids=batch)
            except Exception:
                pass
            meta = {}
        meta["__embedding_model__"] = current
        return meta

    def reindex(self) -> tuple[int, int]:
        now = time.time()
        if now - self._last_scan < SCAN_DEBOUNCE_SECS:
            return 0, 0
        self._last_scan = now

        meta = self.load_meta()
        meta = self._check_embedding_model(meta)
        current_files = self.discover_files()
        current_paths = {str(p.relative_to(self.docs_root)) for p in current_files}

        files_changed = 0
        chunks_added = 0

        # Remove deleted files
        for removed in set(meta.keys()) - current_paths:
            if removed.startswith("__"):
                continue
            self.collection.delete(where={"file_path": removed})
            del meta[removed]

        # Add or update changed files
        for path in current_files:
            rel = str(path.relative_to(self.docs_root))
            mtime_ns = path.stat().st_mtime_ns

            if rel in meta and meta[rel].get("mtime_ns") == mtime_ns:
                continue

            try:
                self.collection.delete(where={"file_path": rel})
            except Exception:
                pass

            file_type = FILE_TYPES.get(path.suffix, "text")

            # Read content once for chunking, description, and title
            # extraction to avoid redundant I/O.
            try:
                content = path.read_text(errors="replace")
            except OSError:
                continue

            file_chunks = self.chunk_file(path, content=content)
            if file_chunks:
                # Deduplicate chunk_paths (e.g. @property + setter pairs
                # or @overload variants) so ChromaDB IDs stay unique.
                seen: dict[str, int] = {}
                for c in file_chunks:
                    cp = c["chunk_path"]
                    if cp in seen:
                        seen[cp] += 1
                        c["chunk_path"] = f"{cp} #{seen[cp]}"
                    else:
                        seen[cp] = 1

                # Attach the file title to each chunk as retrieval context.
                doc_title = _document_title(path, file_type, content=content)

                # E3: extract file-level frontmatter metadata for markdown
                fm_meta: dict[str, str] = {}
                if file_type == "markdown":
                    fm_meta = _extract_frontmatter_meta(content)
                    links = _extract_internal_links(content)
                    if links:
                        fm_meta["links"] = links

                # Embed with a structural prefix for retrieval quality,
                # but store raw content for tools that parse it.
                raw_documents = [c["content"] for c in file_chunks]

                # Build enriched embedding prefix with available signals
                title_part = doc_title
                if fm_meta.get("tags"):
                    title_part += f" [{fm_meta['tags']}]"

                embedding_texts = []
                for c in file_chunks:
                    deco = c.get("decorators", "")
                    cp = f"@{deco} {c['chunk_path']}" if deco else c["chunk_path"]
                    embedding_texts.append(
                        f"{title_part} > {cp}\n\n{c['content']}"
                    )
                embeddings = self._embedding_fn(embedding_texts)

                # Build metadata with passthrough for extra chunk keys
                metadatas = []
                for c in file_chunks:
                    meta_entry = {
                        "file_path": c["file_path"],
                        "chunk_path": c["chunk_path"],
                        "file_type": c["file_type"],
                        "document_title": doc_title,
                        "snippet": chunk_snippet(
                            c["content"], c["file_type"], c["chunk_path"]
                        ),
                    }
                    # Spread file-level frontmatter metadata (E3)
                    meta_entry.update(fm_meta)
                    # Pass through extra chunk-level keys (E5/E6/E7)
                    for k in _EXTRA_CHUNK_KEYS:
                        if k in c:
                            meta_entry[k] = c[k]
                    metadatas.append(meta_entry)

                self.collection.add(
                    ids=[f"{c['file_path']}::{c['chunk_path']}" for c in file_chunks],
                    documents=raw_documents,
                    embeddings=embeddings,
                    metadatas=metadatas,
                )
                chunks_added += len(file_chunks)

            meta[rel] = {
                "mtime_ns": mtime_ns,
                "description": _file_description(path, file_type, content=content),
            }
            files_changed += 1

        self._save_meta(meta)
        return files_changed, chunks_added

    def _save_meta(self, meta: dict) -> None:
        self.meta_path.write_text(json.dumps(meta, indent=2))
