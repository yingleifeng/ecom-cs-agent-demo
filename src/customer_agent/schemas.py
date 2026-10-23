from typing import Any, Literal

from pydantic import BaseModel, Field


Intent = Literal[
    "refund_eligibility",
    "refund_request",
    "exchange_request",
    "refund_status",
    "logistics_issue",
    "policy_faq",
    "unknown",
]
Eligibility = Literal["eligible", "ineligible", "unknown"]
RunMode = Literal["single_agent", "multi_agent"]
ToolMode = Literal["local", "mcp"]
ToolStatus = Literal[
    "success",
    "not_found",
    "forbidden",
    "invalid_argument",
    "timeout",
    "upstream_error",
    "data_incomplete",
]


class CustomerRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    user_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    order_id: str | None = Field(default=None, max_length=128)
    mode: RunMode | None = None
    tool_mode: ToolMode | None = None


class Evidence(BaseModel):
    kind: Literal["none", "policy", "order", "logistics", "after_sales"] = "none"
    summary: str
    source: str | None = None
    rank: int | None = None
    score: float | None = None
    policy_version: str | None = None


class ToolResult(BaseModel):
    status: ToolStatus
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    latency_ms: float = 0.0
    source: str = "mock_data"


class OrderOption(BaseModel):
    order_id: str
    product_name: str
    order_status: str
    ordered_at: str


class CustomerResponse(BaseModel):
    intent: Intent = "unknown"
    intent_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    eligibility: Eligibility = "unknown"
    slot_updates: dict[str, Any] = Field(default_factory=dict)
    session_state: str = "active"
    tools_called: list[str] = Field(default_factory=list)
    clarification_requested: bool = False
    order_options: list[OrderOption] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    policy_version: str | None = None
    next_action: str
    need_human: bool = False
    handoff_reason: str | None = None
    draft_for_human: str | None = None
    trace_id: str
    answer: str


class TraceEvent(BaseModel):
    name: str
    status: Literal["started", "completed", "skipped", "failed"]
    detail: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: float | None = None


class Trace(BaseModel):
    trace_id: str
    request: dict[str, Any]
    response: CustomerResponse | None = None
    events: list[TraceEvent] = Field(default_factory=list)
    total_elapsed_ms: float | None = None
    ttft_ms: float | None = None


class AgentResult(BaseModel):
    response: CustomerResponse
    trace: Trace
