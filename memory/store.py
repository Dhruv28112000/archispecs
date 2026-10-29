"""ChromaDB wrapper for enterprise memory and past runs.

Two access modes (see CLAUDE.md "Memory design"):
- deterministic `get` by type for hard constraints -> get_constraints()
- semantic `query` for guidance (compliance / pattern / feedback) -> search()
"""
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from dotenv import load_dotenv

from schemas import Gap, Memory, UserStory

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
CHROMA_PATH = ROOT / os.getenv("CHROMA_PATH", "memory/chroma")

MEMORY_COLLECTION = "enterprise_memory"
RUNS_COLLECTION = "past_runs"
SEARCH_TYPES = ["compliance", "pattern", "feedback"]

_client: chromadb.ClientAPI | None = None


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _client


def _collection(name: str) -> chromadb.Collection:
    # Cosine space so the UI can show similarity = 1 - distance.
    return _get_client().get_or_create_collection(
        name=name,
        embedding_function=DefaultEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def reset() -> None:
    """Delete both collections (used by seed_memory.py --reset)."""
    client = _get_client()
    for name in (MEMORY_COLLECTION, RUNS_COLLECTION):
        if name in [c.name for c in client.list_collections()]:
            client.delete_collection(name)


def upsert_records(records: list[dict], source: str = "seed") -> int:
    """Upsert memory records {key, type, domain, text[, name]} by stable key. Returns count."""
    metadatas = []
    for r in records:
        meta = {"type": r["type"], "domain": r["domain"], "key": r["key"],
                "source": source, "created_at": _now()}
        if "name" in r:
            meta["name"] = r["name"]
        metadatas.append(meta)
    _collection(MEMORY_COLLECTION).upsert(
        ids=[r["key"] for r in records],
        documents=[r["text"] for r in records],
        metadatas=metadatas,
    )
    return len(records)


def count_by_type() -> dict[str, int]:
    """Return number of memory records per type."""
    counts: dict[str, int] = {}
    for meta in _collection(MEMORY_COLLECTION).get(include=["metadatas"])["metadatas"]:
        counts[meta["type"]] = counts.get(meta["type"], 0) + 1
    return counts


def _get_by_type(type_: str) -> list[tuple[dict, str]]:
    res = _collection(MEMORY_COLLECTION).get(where={"type": type_}, include=["metadatas", "documents"])
    pairs = list(zip(res["metadatas"], res["documents"]))
    return sorted(pairs, key=lambda p: p[0]["key"])


def get_constraints() -> Memory:
    """Build the Memory object with deterministic lookups (never similarity search)."""
    approved_stack = [meta.get("name", meta["key"]) for meta, _ in _get_by_type("stack")]
    compliance_rules = [f"{meta['key']}: {doc}" for meta, doc in _get_by_type("compliance")]
    feedback = [f"{meta['key']}: {doc}" for meta, doc in _get_by_type("feedback")]

    estimation_scale: list[int] = []
    for _, doc in _get_by_type("estimation"):
        match = re.search(r"\[[\d,\s]+\]", doc)
        if match:
            estimation_scale = json.loads(match.group(0))
            break
    if not estimation_scale:
        raise ValueError("No estimation scale found in memory — run memory/seed_memory.py")

    return Memory(approved_stack=approved_stack, compliance_rules=compliance_rules,
                  estimation_scale=estimation_scale, feedback=feedback)


def _query(collection_name: str, queries: list[str], n: int, where: dict | None) -> list[dict]:
    """Run each query, merge results, keep the best distance per id, sort by distance."""
    collection = _collection(collection_name)
    total = collection.count()
    if total == 0 or not queries:
        return []
    res = collection.query(query_texts=queries, n_results=min(n, total), where=where,
                           include=["metadatas", "documents", "distances"])
    best: dict[str, dict] = {}
    for ids, metas, docs, dists in zip(res["ids"], res["metadatas"], res["documents"], res["distances"]):
        for id_, meta, doc, dist in zip(ids, metas, docs, dists):
            if id_ not in best or dist < best[id_]["distance"]:
                best[id_] = {**meta, "id": id_, "text": doc, "distance": round(dist, 4)}
    return sorted(best.values(), key=lambda r: r["distance"])


def search(queries: list[str], n: int = 5) -> list[dict]:
    """Semantic search over compliance/pattern/feedback records.

    Returns the top `n` per query, merged and de-duplicated, sorted by distance.
    Each dict has key, type, domain, text, distance (cosine; lower = more similar).
    """
    return _query(MEMORY_COLLECTION, queries, n, where={"type": {"$in": SEARCH_TYPES}})


def search_past(queries: list[str], n: int = 3) -> list[dict]:
    """Semantic search over approved gaps/stories from previous runs."""
    return _query(RUNS_COLLECTION, queries, n, where=None)


def add_feedback(text: str, domain: str = "general") -> str:
    """Store user feedback as a type=feedback record. Returns its key."""
    key = f"feedback-{uuid.uuid4().hex[:8]}"
    upsert_records([{"key": key, "type": "feedback", "domain": domain, "text": text}],
                   source="user_feedback")
    return key


def add_run(run_id: str, gaps: list[Gap], stories: list[UserStory], domain: str = "general") -> int:
    """Store approved gaps and stories from a run in past_runs. Returns number stored."""
    ids, docs, metas = [], [], []
    for g in gaps:
        ids.append(f"{run_id}-{g.id}")
        docs.append(f"{g.title}. {g.reason} Suggested: {g.suggested_requirement}")
        metas.append({"run_id": run_id, "kind": "gap", "domain": domain, "created_at": _now()})
    for s in stories:
        ids.append(f"{run_id}-{s.id}")
        docs.append(f"{s.title}. As a {s.as_a}, I want {s.i_want}, so that {s.so_that}.")
        metas.append({"run_id": run_id, "kind": "story", "domain": domain, "created_at": _now()})
    if ids:
        _collection(RUNS_COLLECTION).upsert(ids=ids, documents=docs, metadatas=metas)
    return len(ids)
