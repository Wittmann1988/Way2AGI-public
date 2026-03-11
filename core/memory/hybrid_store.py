# core/memory/hybrid_store.py
"""
Layer 2+3: Hybrid Store (Vector + Knowledge Graph)
===================================================
Vector: ChromaDB or SQLite FTS fallback
Graph: NetworkX in-memory + SQLite persistence
"""

import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    from core.config import config
except ImportError:
    config = None  # type: ignore[assignment]

log = logging.getLogger("way2agi.memory.hybrid")

DB_PATH = str(
    config.PROJECT_ROOT / "memory" / "memory.db" if config else Path.home() / ".way2agi" / "memory" / "memory.db"
)


class HybridStore:
    """Combined vector similarity + knowledge graph store."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._chroma = None
        self._graph = None
        self._init_backends()

    def _init_backends(self):
        # Try ChromaDB for vector search
        try:
            import chromadb
            self._chroma = chromadb.Client()
            self._collection = self._chroma.get_or_create_collection("way2agi_memory")
            log.info("Vector backend: ChromaDB")
        except ImportError:
            log.info("Vector backend: SQLite FTS fallback (install chromadb for better search)")

        # Try NetworkX for graph
        try:
            import networkx as nx
            self._graph = nx.DiGraph()
            self._load_graph_from_db()
            log.info("Graph backend: NetworkX")
        except ImportError:
            log.info("Graph backend: SQLite relations fallback")

    def _load_graph_from_db(self):
        """Load existing relations from SQLite into NetworkX graph."""
        if not self._graph:
            return
        try:
            db = sqlite3.connect(self.db_path, timeout=10)
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT source, relation, target FROM relations"
            ).fetchall()
            for r in rows:
                self._graph.add_edge(r["source"], r["target"], relation=r["relation"])
            db.close()
            log.info("Graph loaded: %d edges", self._graph.number_of_edges())
        except Exception as e:
            log.debug("Graph load failed: %s", e)

    async def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """Vector similarity search."""
        # ChromaDB path
        if self._chroma and self._collection:
            try:
                results = self._collection.query(query_texts=[query], n_results=top_k)
                return [
                    {
                        "layer": 2,
                        "type": "vector",
                        "content": doc,
                        "relevance": 1.0 - dist if dist else 0.5,
                    }
                    for doc, dist in zip(
                        results.get("documents", [[]])[0],
                        results.get("distances", [[]])[0],
                    )
                ]
            except Exception as e:
                log.debug("ChromaDB search failed: %s", e)

        # SQLite FTS fallback
        try:
            db = sqlite3.connect(self.db_path, timeout=10)
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT content, importance FROM memories "
                "WHERE content LIKE ? ORDER BY importance DESC LIMIT ?",
                (f"%{query}%", top_k),
            ).fetchall()
            db.close()
            return [
                {
                    "layer": 2,
                    "type": "vector_fallback",
                    "content": dict(r)["content"],
                    "relevance": dict(r).get("importance", 0.5),
                }
                for r in rows
            ]
        except Exception as e:
            log.debug("SQLite search failed: %s", e)
            return []

    async def store_vector(self, interaction: Dict[str, Any]):
        """Store interaction as vector embedding."""
        content = f"{interaction.get('prompt', '')} {interaction.get('response', '')}"
        doc_id = f"mem_{int(interaction.get('timestamp', time.time()))}"

        if self._chroma and self._collection:
            try:
                self._collection.add(documents=[content[:2000]], ids=[doc_id])
            except Exception as e:
                log.debug("ChromaDB store failed: %s", e)

    async def store_graph(self, interaction: Dict[str, Any]):
        """Extract and store knowledge graph relations."""
        if not self._graph:
            return
        # Simple entity extraction (kann spaeter durch NER ersetzt werden)
        prompt = interaction.get("prompt", "")
        response = interaction.get("response", "")
        # Store as interaction edge
        self._graph.add_edge(
            f"user_query_{int(time.time())}",
            f"response_{int(time.time())}",
            relation="answered_by",
            content=prompt[:200],
        )
