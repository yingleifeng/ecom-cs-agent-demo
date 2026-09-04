from .config import Settings
from .observability import TraceRecorder
from .schemas import AgentResult, CustomerRequest, CustomerResponse


class CustomerAgent:
    """Ticket-01 baseline orchestration seam.

    This baseline deliberately does not call a model, database, RAG index, or write tool.
    Later tickets plug those capabilities into this same entry point.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()

    def handle(
        self,
        message: str,
        user_id: str,
        session_id: str,
        order_id: str | None = None,
        mode: str = "single_agent",
        tool_mode: str = "local",
    ) -> CustomerResponse:
        request = CustomerRequest(
            message=message,
            user_id=user_id,
            session_id=session_id,
            order_id=order_id,
            mode=mode,
            tool_mode=tool_mode,
        )
        return self.handle_request(request).response

    def handle_request(self, request: CustomerRequest) -> AgentResult:
        recorder = TraceRecorder(request.model_dump())
        recorder.event("orchestration", "started", {"mode": request.mode})
        recorder.event("intent_classification", "skipped", {"reason": "ticket_01_baseline"})
        response = CustomerResponse(
            intent="unknown",
            intent_confidence=0.0,
            eligibility="unknown",
            next_action="请补充您要咨询的订单号；如果仍无法定位订单，我们会为您转人工客服。",
            need_human=False,
            trace_id=recorder.trace.trace_id,
            answer=(
                "您好，我可以协助查询退款/退货问题。当前基础版本还未接入订单查询，"
                "请先提供订单号，后续系统会根据订单、物流和售后信息给出判断。"
            ),
        )
        recorder.event("response_rendering", "completed")
        recorder.event("orchestration", "completed")
        trace = recorder.finish(response)
        return AgentResult(response=response, trace=trace)
