import re
import time
import uuid
from typing import Any

from .schemas import CustomerResponse, Trace, TraceEvent


def new_trace_id() -> str:
    return f"tr_{uuid.uuid4().hex[:16]}"


def redact(value: Any) -> Any:
    """Redact common sensitive values before they enter a trace."""
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    value = re.sub(r"(?<!\d)(1\d{10})(?!\d)", "[手机号已脱敏]", value)
    value = re.sub(r"\b\d{16,19}\b", "[敏感数字已脱敏]", value)
    return value


class TraceRecorder:
    def __init__(self, request: dict[str, Any]) -> None:
        self.trace = Trace(trace_id=new_trace_id(), request=redact(request))
        self._started = time.perf_counter()

    def event(self, name: str, status: str, detail: dict[str, Any] | None = None) -> None:
        self.trace.events.append(
            TraceEvent(name=name, status=status, detail=redact(detail or {}))
        )

    def finish(self, response: CustomerResponse) -> Trace:
        self.trace.response = response
        self.trace.total_elapsed_ms = round((time.perf_counter() - self._started) * 1000, 2)
        self.trace.ttft_ms = self.trace.total_elapsed_ms
        return self.trace
