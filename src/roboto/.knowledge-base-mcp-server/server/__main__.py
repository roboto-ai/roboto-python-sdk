"""knowledge-base-roboto -- Roboto Python SDK source code and client library"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import chromadb
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext

from .indexer import Indexer
from .tools import register_tools


class IndexOnConnect(Middleware):
    """Trigger an incremental reindex when a client connects."""

    def __init__(self, indexer: Indexer) -> None:
        self._indexer = indexer

    async def on_initialize(self, context: MiddlewareContext, call_next):
        result = await call_next(context)
        files_changed, chunks_added = await asyncio.to_thread(self._indexer.reindex)
        print(
            f"Indexed {files_changed} files, {chunks_added} chunks.",
            file=sys.stderr,
        )
        return result


parser = argparse.ArgumentParser()
parser.add_argument(
    "--docs-root",
    default="..",
    help="root directory of documents to index",
)
parser.add_argument(
    "--index-only",
    action="store_true",
    help="run a full index then exit without starting the server",
)
parser.add_argument(
    "--embedding-model",
    default=None,
    help="SentenceTransformer model name (default: ChromaDB default)",
)
args = parser.parse_args()

docs_root = Path(args.docs_root).resolve()
kb_dir = docs_root / ".knowledge-base-mcp-server"

embedding_fn = None
if args.embedding_model:
    from chromadb.utils.embedding_functions import (
        SentenceTransformerEmbeddingFunction,
    )

    embedding_fn = SentenceTransformerEmbeddingFunction(model_name=args.embedding_model)

client = chromadb.PersistentClient(path=str(kb_dir / "chroma"))

create_kwargs: dict = {
    "name": "chunks",
    "configuration": {"hnsw": {"space": "cosine"}},
}
if embedding_fn is not None:
    create_kwargs["embedding_function"] = embedding_fn
collection = client.get_or_create_collection(**create_kwargs)

indexer = Indexer(collection, docs_root, kb_dir, embedding_fn=embedding_fn)

if args.index_only:
    files_changed, chunks_added = indexer.reindex()
    print(
        f"Indexed {files_changed} files, {chunks_added} chunks.",
        file=sys.stderr,
    )
    sys.exit(0)

mcp = FastMCP(
    "knowledge-base-roboto",
    instructions=(
        """Source code for the Roboto Python SDK, the public client library for the Roboto robotics data management platform (roboto.ai). The SDK provides domain model classes, HTTP client, CLI, and utilities for managing robotics data.

Domain entities (in domain/): Actions (reusable data-processing functions), Invocations (action executions), Triggers (automatic invocation rules), Datasets (data containers), Files (individual file records with upload/download), Collections (curated groups of datasets), Topics (message-path time-series data with representations), Events (annotations on data), Devices, Users, Orgs, Secrets, Tokens, Comments, and Layouts.

Key infrastructure modules: http/ (HttpClient, RobotoClient, request decorators, error handling, retry logic), fs/ (file-system abstraction, object-store integration, signed-URL uploads), auth/ (OpenFGA permissions, scopes), query/ (query specification and visitor pattern), upload_agent/ (parallel upload orchestration), ai/ (chat and AI summary), analytics/ (signal similarity matching), config (RobotoConfig), sentinels (NotSet pattern), and pydantic validators/serializers.

CLI (cli/): Click-based command groups for actions, datasets, collections, images, invocations, devices, secrets, tokens, triggers, users, orgs, cache, and chat.

275 Python source files across 52 directories, organized as a well-structured Python package with __init__.py re-exports.\n\n"""
        "Use `search` for semantic lookup, `list_documents` to browse files, "
        "`get_table_of_contents` for structure, `get_section` to read content, "
        "`get_document_summary` for file overviews, `get_related` for similar "
        """sections, and `describe_collection` for corpus guidance.\n\n"""
        "Start here when exploring a topic — this knowledge base is the "
        "fastest way to find relevant files, understand structure, and build context."
        "However, when results reference source code, verify against "
        "the live codebase (via code navigation, symbol search, or file reads)."
    ),
)
register_tools(mcp, indexer)
mcp.add_middleware(IndexOnConnect(indexer))

print("Server ready", file=sys.stderr)
mcp.run(transport="stdio")
