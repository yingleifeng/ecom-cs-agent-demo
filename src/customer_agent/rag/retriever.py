from pathlib import Path

from ..schemas import Evidence
from .chunker import chunk_markdown
from .vector_store import LocalVectorStore

# 知识库文件列表：主政策文件 + 各专题 FAQ
_KNOWLEDGE_FILES = [
    "policy_v1.0.md",
    "knowledge/refund_policy_v2.0.md",
    "knowledge/logistics_faq_v2.0.md",
    "knowledge/product_order_faq_v1.0.md",
    "knowledge/product_exception_rules_v1.0.md",
    "knowledge/handoff_guidelines_v1.0.md",
]


class PolicyRetriever:
    """Transparent markdown chunking + local vector recall for the demo RAG.

    Indexes all knowledge base files under data/ so queries can retrieve
    relevant chunks from the full policy and FAQ corpus.
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path(__file__).resolve().parents[3] / "data"
        self.policy_version = "policy_v2.0"
        chunks = []
        for relative in _KNOWLEDGE_FILES:
            path = self.data_dir / relative
            if path.exists():
                text = path.read_text(encoding="utf-8")
                chunks.extend(chunk_markdown(text, path.name))
        self.chunks = chunks
        self.vector_store = LocalVectorStore(self.chunks)

    def search(self, query: str) -> list[Evidence]:
        hits = self.vector_store.search(query, top_k=3)
        return [
            Evidence(
                kind="policy",
                summary=f"[{hit.chunk.chunk_id}] {hit.chunk.heading}：{hit.chunk.content}",
                source=f"{hit.chunk.section}#{hit.chunk.heading}#{hit.chunk.chunk_id}",
                rank=rank,
                score=round(hit.score, 4),
                policy_version=self.policy_version,
            )
            for rank, hit in enumerate(hits, start=1)
        ]
