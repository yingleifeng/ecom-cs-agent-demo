import re
import time
import uuid
from typing import Any

from .schemas import CustomerResponse, Trace, TraceEvent


def new_trace_id() -> str:
    return f"tr_{uuid.uuid4().hex[:16]}"


def redact(value: Any) -> Any:
    """Redact common personal and payment data before it enters observability data."""
    if isinstance(value, dict):
        sensitive_key = re.compile(r"(?:phone|mobile|telephone|address|street|card|bank|payment|手机号|电话|地址|银行卡|支付账号|支付信息)", re.I)
        return {
            key: "[敏感信息已脱敏]" if sensitive_key.search(str(key)) and item not in (None, "") else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    value = re.sub(r"(?<!\d)(?:\+?86[- ]?)?(1\d{10})(?!\d)", "[手机号已脱敏]", value)
    value = re.sub(r"(?<!\d)(?:\d[ -]*?){16,19}(?!\d)", "[支付卡号已脱敏]", value)
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已脱敏]", value)
    value = re.sub(
        r"((?:详细)?地址|收货地址|银行卡号|银行卡|支付账号|支付宝账号|微信支付账号)\s*[:：是为]*\s*[^，。；;\n]+",
        r"\1：[敏感信息已脱敏]",
        value,
        flags=re.I,
    )
    return value


class TraceRecorder:
    def __init__(self, request: dict[str, Any]) -> None:
        self.trace = Trace(trace_id=new_trace_id(), request=redact(request))
        self._started = time.perf_counter()

    def event(self, name: str, status: str, detail: dict[str, Any] | None = None) -> None:
        safe_detail = redact(detail or {})
        elapsed = safe_detail.get("latency_ms")
        self.trace.events.append(
            TraceEvent(
                name=name,
                status=status,
                detail=safe_detail,
                elapsed_ms=float(elapsed) if isinstance(elapsed, (int, float)) else None,
            )
        )

    def finish(self, response: CustomerResponse) -> Trace:
        self.trace.response = CustomerResponse.model_validate(redact(response.model_dump()))
        self.trace.total_elapsed_ms = round((time.perf_counter() - self._started) * 1000, 2)
        self.trace.ttft_ms = self.trace.total_elapsed_ms
        return self.trace
