from pathlib import Path

from ..schemas import Evidence


class PolicyRetriever:
    """Small transparent keyword retriever used before a vector backend is added."""

    def __init__(self, policy_path: Path | None = None) -> None:
        self.policy_path = policy_path or Path(__file__).resolve().parents[3] / "data" / "policy_v1.0.md"
        self.policy_version = "policy_v1.0"
        self.sections = self._load_sections()

    def _load_sections(self) -> list[tuple[str, str]]:
        text = self.policy_path.read_text(encoding="utf-8")
        sections: list[tuple[str, str]] = []
        title = "政策"
        body: list[str] = []
        for line in text.splitlines():
            if line.startswith("## "):
                if body:
                    sections.append((title, "\n".join(body).strip()))
                    body = []
                title = line[3:].strip()
            elif line.strip() and not line.startswith("# "):
                body.append(line.strip())
        if body:
            sections.append((title, "\n".join(body).strip()))
        return sections

    def search(self, query: str) -> list[Evidence]:
        normalized = query.lower()
        vocabulary = [
            "退款", "退货", "未发货", "已发货", "签收", "特殊商品", "定制",
            "易腐", "贴身", "售后", "物流", "订单", "人工",
        ]
        terms = {term for term in vocabulary if term in normalized}
        ranked = []
        for title, body in self.sections:
            score = sum(1 for term in terms if term and (term in title.lower() or term in body.lower()))
            if score:
                ranked.append((score, title, body))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [Evidence(kind="policy", summary=f"{title}：{body}", source=f"policy_v1.0.md#{title}") for _, title, body in ranked[:2]]
