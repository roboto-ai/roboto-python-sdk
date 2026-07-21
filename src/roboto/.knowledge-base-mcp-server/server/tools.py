"""MCP tool definitions for Roboto Python SDK source code and client library."""

from __future__ import annotations

from pathlib import Path

from .indexer import FILE_TYPES, Indexer, chunk_snippet


def _build_where(
    path: str | None = None,
    file_type: str | None = None,
    tags: str | None = None,
) -> dict | None:
    """Build a ChromaDB ``where`` filter from optional constraints.

    Note: ``file_type`` uses ``$contains`` because callers pass partial types
    like ``"code"`` to match both ``"code:python"`` and ``"code:typescript"``.
    ``file_path`` also uses ``$contains`` because ChromaDB lacks a
    ``$startswith`` operator; this means a path filter like ``"src/"`` could
    match ``"vendor/src/"`` in theory, though in practice all paths are
    relative to the docs root so false positives are rare.
    ``tags`` uses ``$contains`` because tags are stored as a comma-separated
    string (e.g. ``"tutorial, beginner"``), so substring matching lets
    callers filter by a single tag.
    """
    conditions: list[dict] = []
    if path:
        conditions.append({"file_path": {"$contains": path}})
    if file_type:
        conditions.append({"file_type": {"$contains": file_type}})
    if tags:
        conditions.append({"tags": {"$contains": tags}})
    if len(conditions) > 1:
        return {"$and": conditions}
    return conditions[0] if conditions else None


def register_tools(mcp, indexer: Indexer) -> None:
    """Register all MCP tools on *mcp* backed by *indexer*."""
    collection = indexer.collection

    @mcp.tool
    def describe_collection() -> str:
        """Describe this knowledge base and what questions it can answer.

        Source code for the Roboto Python SDK, the public client library for the Roboto robotics data management platform (roboto.ai). The SDK provides domain model classes, HTTP client, CLI, and utilities for managing robotics data.

Domain entities (in domain/): Actions (reusable data-processing functions), Invocations (action executions), Triggers (automatic invocation rules), Datasets (data containers), Files (individual file records with upload/download), Collections (curated groups of datasets), Topics (message-path time-series data with representations), Events (annotations on data), Devices, Users, Orgs, Secrets, Tokens, Comments, and Layouts.

Key infrastructure modules: http/ (HttpClient, RobotoClient, request decorators, error handling, retry logic), fs/ (file-system abstraction, object-store integration, signed-URL uploads), auth/ (OpenFGA permissions, scopes), query/ (query specification and visitor pattern), upload_agent/ (parallel upload orchestration), ai/ (chat and AI summary), analytics/ (signal similarity matching), config (RobotoConfig), sentinels (NotSet pattern), and pydantic validators/serializers.

CLI (cli/): Click-based command groups for actions, datasets, collections, images, invocations, devices, secrets, tokens, triggers, users, orgs, cache, and chat.

275 Python source files across 52 directories, organized as a well-structured Python package with __init__.py re-exports.

        Returns:
            The corpus description followed by usage guidance for the other
            tools in this server.
        """
        return (
            """Source code for the Roboto Python SDK, the public client library for the Roboto robotics data management platform (roboto.ai). The SDK provides domain model classes, HTTP client, CLI, and utilities for managing robotics data.

Domain entities (in domain/): Actions (reusable data-processing functions), Invocations (action executions), Triggers (automatic invocation rules), Datasets (data containers), Files (individual file records with upload/download), Collections (curated groups of datasets), Topics (message-path time-series data with representations), Events (annotations on data), Devices, Users, Orgs, Secrets, Tokens, Comments, and Layouts.

Key infrastructure modules: http/ (HttpClient, RobotoClient, request decorators, error handling, retry logic), fs/ (file-system abstraction, object-store integration, signed-URL uploads), auth/ (OpenFGA permissions, scopes), query/ (query specification and visitor pattern), upload_agent/ (parallel upload orchestration), ai/ (chat and AI summary), analytics/ (signal similarity matching), config (RobotoConfig), sentinels (NotSet pattern), and pydantic validators/serializers.

CLI (cli/): Click-based command groups for actions, datasets, collections, images, invocations, devices, secrets, tokens, triggers, users, orgs, cache, and chat.

275 Python source files across 52 directories, organized as a well-structured Python package with __init__.py re-exports.\n\n"""
            "Start here when exploring a topic — this knowledge base is the "
            "fastest way to find relevant files, understand structure, and "
            "build context. Use the other tools in this server to search, "
            """browse, and read the indexed content.\n\n"""
            "When results reference source code, verify against the live codebase."
        )

    @mcp.tool
    def list_documents(path: str | None = None, file_type: str | None = None) -> str:
        """List indexed files in Roboto Python SDK source code and client library.

        Args:
            path: Subdirectory prefix to filter by (relative to docs root),
                e.g. 'guides/' or 'src/utils/'. Omit to list all files.
            file_type: Filter by type. Supported values: ``"markdown"``,
                ``"code"``, ``"text"``, ``"data"``. Substring matching is used,
                so ``"code"`` matches both ``"code:python"`` and
                ``"code:typescript"``. Omit to list all types.

        Returns:
            One line per file in the format
            ``<path>  [<type>]  <description>``, or ``"No files found."``
            if nothing matches the filters.

        Example::

            list_documents(path='guides/', file_type='markdown')
            list_documents()  # all files
        """
        indexer.reindex()
        meta = indexer.load_meta()
        lines: list[str] = []
        for fp, info in sorted(meta.items()):
            if fp.startswith("__"):
                continue
            if path and not fp.startswith(path):
                continue
            ft = FILE_TYPES.get(Path(fp).suffix, "text")
            if file_type and file_type not in ft:
                continue
            desc = info.get("description", "")
            lines.append(f"{fp}  [{ft}]  {desc}")
        return "\n".join(lines) if lines else "No files found."

    @mcp.tool
    def get_table_of_contents(path: str | None = None) -> str:
        """Outline one file or the entire collection of Roboto Python SDK source code and client library.

        Returns file paths with their chunk_path values indented beneath them.
        Pass the chunk_path values to ``get_section`` or ``get_related``.

        Args:
            path: File path relative to docs root, e.g. 'guides/testing.md'.
                Omit for an outline of the full collection.

        Returns:
            An indented listing of files and their chunk_path entries, e.g.::

                guides/testing.md
                  Getting Started
                  Getting Started > Prerequisites
                  Getting Started > Running Tests

            Returns ``"No content found."`` if nothing matches.

        Example::

            get_table_of_contents(path='guides/testing.md')
            get_table_of_contents()  # entire collection
        """
        indexer.reindex()
        where = {"file_path": path} if path else None
        result = collection.get(where=where, include=["metadatas"])

        entries: dict[str, list[str]] = {}
        for m in result["metadatas"]:
            entries.setdefault(m["file_path"], []).append(m["chunk_path"])

        lines: list[str] = []
        for fp in sorted(entries):
            lines.append(fp)
            for cp in entries[fp]:
                lines.append(f"  {cp}")
        return "\n".join(lines) if lines else "No content found."

    @mcp.tool
    def get_section(path: str, chunk_path: str) -> str:
        """Retrieve the full text of a section in Roboto Python SDK source code and client library.

        Call ``get_table_of_contents`` first to discover valid ``chunk_path``
        values. When no exact match exists, falls back to substring matching
        and returns the closest match with a note.

        Args:
            path: File path relative to docs root, e.g. ``'guides/testing.md'``.
            chunk_path: The ``chunk_path`` identifier from
                ``get_table_of_contents`` or ``search``. For markdown files
                this is the heading hierarchy joined by ``' > '``, e.g.
                ``'Getting Started > Prerequisites'``. For code files this is
                the symbol declaration, e.g. ``'class Router'`` or
                ``'def process_event'``.

        Returns:
            The full text of the matched section, followed by navigation
            links to the previous and next sections in the same file.
            Returns ``"Chunk not found: <id>"`` if no match exists.

        Example::

            get_section(path='guides/testing.md',
                        chunk_path='Getting Started > Prerequisites')
            get_section(path='src/router.py', chunk_path='class Router')
        """
        indexer.reindex()
        chunk_id = f"{path}::{chunk_path}"
        result = collection.get(ids=[chunk_id], include=["documents", "metadatas"])

        if result["documents"]:
            text = result["documents"][0]
        else:
            file_chunks = collection.get(
                where={"file_path": path}, include=["documents", "metadatas"]
            )
            best = None
            best_direct = False  # whether best matched via chunk_path
            query_lower = chunk_path.lower()
            for i, m in enumerate(file_chunks["metadatas"]):
                cp_lower = m["chunk_path"].lower()
                # Also check _merged_paths so individual symbol names
                # within merged chunks remain navigable (E7).
                merged_lower = m.get("_merged_paths", "").lower()
                in_cp = query_lower in cp_lower
                in_merged = query_lower in merged_lower
                if in_cp or in_merged:
                    # Prefer direct chunk_path matches over _merged_paths
                    # matches, then shortest chunk_path among same type.
                    if best is None:
                        best, best_direct = i, in_cp
                    elif in_cp and not best_direct:
                        best, best_direct = i, True
                    elif in_cp == best_direct and len(cp_lower) < len(
                        file_chunks["metadatas"][best]["chunk_path"]
                    ):
                        best = i
            if best is not None:
                cp = file_chunks["metadatas"][best]["chunk_path"]
                text = f"(Closest match: {cp})\n\n{file_chunks['documents'][best]}"
            else:
                return f"Chunk not found: {chunk_id}"

        # Append prev/next navigation links
        all_chunks = collection.get(where={"file_path": path}, include=["metadatas"])
        paths = [m["chunk_path"] for m in all_chunks["metadatas"]]
        try:
            idx = paths.index(chunk_path)
        except ValueError:
            idx = -1

        nav: list[str] = []
        if idx > 0:
            nav.append(f"\u2190 Previous: {paths[idx - 1]}")
        if 0 <= idx < len(paths) - 1:
            nav.append(f"\u2192 Next: {paths[idx + 1]}")
        if nav:
            text += "\n\n---\n" + "  |  ".join(nav)

        return text

    @mcp.tool
    def search(
        query: str,
        path: str | None = None,
        file_type: str | None = None,
        tags: str | None = None,
        limit: int = 10,
    ) -> str:
        """Semantic search across Roboto Python SDK source code and client library.

        Embeds the query and returns the closest chunks ranked by distance.
        Each result includes the file path, chunk_path, distance score,
        document title, and a one-line snippet. Pass the returned
        ``chunk_path`` values to ``get_section`` to read the full text.

        Args:
            query: Natural-language search query.
            path: Subdirectory prefix to restrict results to, e.g.
                ``'guides/'``. Omit to search all files.
            file_type: Filter by type: ``"markdown"``, ``"code"``, ``"text"``,
                ``"data"``. Substring matching, so ``"code"`` matches both
                ``"code:python"`` and ``"code:typescript"``. Omit for all.
            tags: Filter by frontmatter tag (substring match on the tags
                metadata field, which stores tags as a comma-separated
                string). E.g. ``'tutorial'`` matches a file with tags
                ``"tutorial, beginner"``. Omit for all.
            limit: Maximum number of results to return. Defaults to 10.

        Returns:
            Newline-separated result entries in the format::

                [<distance>] <file_path> :: <chunk_path>  (<document_title>)
                  <snippet>

            Returns ``"No results found."`` if nothing matches.

        Example::

            search(query='how to configure authentication')
            search(query='error handling', path='src/', file_type='code')
            search(query='getting started', tags='tutorial')
        """
        indexer.reindex()
        where = _build_where(path, file_type, tags)
        kwargs: dict[str, object] = {"query_texts": [query], "n_results": limit}
        if where:
            kwargs["where"] = where

        results = collection.query(**kwargs)

        lines: list[str] = []
        for i in range(len(results["ids"][0])):
            dist = results["distances"][0][i]
            meta = results["metadatas"][0][i]
            ft = meta.get("file_type", "text")
            snippet = meta.get("snippet") or chunk_snippet(
                results["documents"][0][i], ft, meta["chunk_path"]
            )
            title = meta.get("document_title", "")
            header = f"[{dist:.3f}] {meta['file_path']} :: {meta['chunk_path']}"
            if title:
                header += f"  ({title})"
            lines.append(f"{header}\n  {snippet}")
        return "\n\n".join(lines) if lines else "No results found."

    @mcp.tool
    def get_document_summary(path: str) -> str:
        """Structural summary of a file in Roboto Python SDK source code and client library.

        Returns an outline with a one-line description per section, ranked by
        cosine similarity to the document's centroid embedding. Descriptions
        are type-aware: first sentence for prose, docstring or signature for
        code, shape for data files.

        Args:
            path: File path relative to docs root, e.g. ``'guides/testing.md'``.

        Returns:
            Newline-separated entries in the format
            ``**<chunk_path>** — <description>``, ordered by relevance.
            Returns ``"File not found: <path>"`` if the file is not indexed.

        Example::

            get_document_summary(path='guides/testing.md')
            get_document_summary(path='src/router.py')
        """
        indexer.reindex()
        result = collection.get(
            where={"file_path": path},
            include=["documents", "metadatas", "embeddings"],
        )

        if not result["documents"]:
            return f"File not found: {path}"

        n = len(result["documents"])
        file_type = result["metadatas"][0].get("file_type", "text") if n else "text"

        # Rank sections by cosine similarity to the centroid so the most
        # representative sections appear first.
        order = list(range(n))
        if result.get("embeddings") is not None and n > 1:
            try:
                embs = result["embeddings"]
                dim = len(embs[0])
                # Arithmetic mean centroid
                centroid = [sum(embs[j][d] for j in range(n)) / n for d in range(dim)]
                c_norm = sum(x * x for x in centroid) ** 0.5

                similarities: list[tuple[float, int]] = []
                for j in range(n):
                    dot = sum(embs[j][d] * centroid[d] for d in range(dim))
                    e_norm = sum(x * x for x in embs[j]) ** 0.5
                    sim = dot / (e_norm * c_norm) if e_norm and c_norm else 0.0
                    similarities.append((sim, j))
                similarities.sort(reverse=True)
                order = [idx for _, idx in similarities]
            except Exception:
                pass  # fall back to insertion order

        lines: list[str] = []
        for i in order:
            meta = result["metadatas"][i]
            doc = result["documents"][i]
            cp = meta["chunk_path"]
            ft = meta.get("file_type", file_type)
            desc = meta.get("snippet") or chunk_snippet(doc, ft, cp)
            lines.append(f"**{cp}** — {desc}")

        return "\n".join(lines)

    @mcp.tool
    def get_related(path: str, chunk_path: str, limit: int = 5) -> str:
        """Find sections similar to a given section in Roboto Python SDK source code and client library.

        Uses the source section's embedding to query for nearest neighbours,
        excluding the source itself.

        Args:
            path: File path relative to docs root, e.g. ``'guides/testing.md'``.
            chunk_path: The ``chunk_path`` identifier of the source section,
                as returned by ``get_table_of_contents`` or ``search``.
            limit: Maximum number of results to return. Defaults to 5.

        Returns:
            Newline-separated entries in the format::

                [<distance>] <file_path> :: <chunk_path>
                  <snippet>

            Returns ``"Chunk not found: <id>"`` if the source section does
            not exist, or ``"No related chunks found."`` if there are no
            similar sections.

        Example::

            get_related(path='guides/testing.md',
                        chunk_path='Getting Started > Prerequisites')
            get_related(path='src/router.py', chunk_path='class Router',
                        limit=3)
        """
        indexer.reindex()
        source_id = f"{path}::{chunk_path}"
        source = collection.get(ids=[source_id], include=["embeddings"])

        if not source["embeddings"]:
            return f"Chunk not found: {source_id}"

        embedding = source["embeddings"][0]
        results = collection.query(query_embeddings=[embedding], n_results=limit + 1)

        lines: list[str] = []
        for i in range(len(results["ids"][0])):
            if results["ids"][0][i] == source_id:
                continue
            dist = results["distances"][0][i]
            meta = results["metadatas"][0][i]
            ft = meta.get("file_type", "text")
            snippet = meta.get("snippet") or chunk_snippet(
                results["documents"][0][i], ft, meta["chunk_path"]
            )
            lines.append(
                f"[{dist:.3f}] {meta['file_path']} :: {meta['chunk_path']}\n  {snippet}"
            )
        return "\n\n".join(lines[:limit]) if lines else "No related chunks found."
