from pathlib import Path

from ..schemas import Evidence
from .chunker import chunk_markdown
from .vector_store import LocalVectorStore


class PolicyRetriever:
    """Transparent markdown chunking + local vector recall for the demo RAG."""

    def __init__(self, policy_path: Path | None = None) -> None:
        self.policy_path = policy_path or Path(__file__).resolve().parents[3] / "data" / "policy_v1.0.md"
        self.policy_version = "policy_v1.0"
        self.text = self.policy_path.read_text(encoding="utf-8")
        self.chunks = chunk_markdown(self.text, self.policy_path.name)
        self.vector_store = LocalVectorStore(self.chunks)

    def search(self, query: str) -> list[Evidence]:
        hits = self.vector_store.search(query, top_k=3)
        return [
            Evidence(
                kind="policy",
                summary=f"[{hit.chunk.chunk_id}] {hit.chunk.heading}：{hit.chunk.content}",
                source=f"{hit.chunk.section}#{hit.chunk.heading}#{hit.chunk.chunk_id}",
            )
            for hit in hits
        ]
