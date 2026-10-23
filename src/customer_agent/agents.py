"""Small, deterministic role agents used by the multi-agent comparison mode.

The demo has no LLM provider yet. These roles delegate to the same local policy,
tool and decision contracts as single-agent mode and make responsibility boundaries
observable without inventing token usage or model costs.
"""

from typing import Any, Callable

from .schemas import CustomerResponse, Evidence, ToolResult
from .session import classify_intent


class OrchestrationAgent:
    def classify(self, message: str, previous_intent: str | None) -> tuple[str, float]:
        return classify_intent(message, previous_intent)

    @staticmethod
    def summarize(response: CustomerResponse) -> dict[str, Any]:
        return {
            "intent": response.intent,
            "eligibility": response.eligibility,
            "need_human": response.need_human,
        }


class PolicyAgent:
    """Retrieves and arranges policy evidence; it never decides eligibility."""

    @staticmethod
    def retrieve(retriever: Any, query: str) -> list[Evidence]:
        return retriever.search(query)


class FactsAgent:
    """Calls the injected read-only tool operation without interpreting its facts."""

    @staticmethod
    def query(operation: Callable[..., ToolResult], *arguments: Any) -> ToolResult:
        return operation(*arguments)


class HandoffAgent:
    """Builds a privacy-safe handoff summary from orchestrator-provided context."""

    @staticmethod
    def summarize(builder: Callable[[], str]) -> str:
        return builder()
