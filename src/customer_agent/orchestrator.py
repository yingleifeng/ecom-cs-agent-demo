from .config import Settings
from .decision import decide_refund
from .observability import TraceRecorder
from .rag import PolicyRetriever
from .schemas import AgentResult, CustomerRequest, CustomerResponse, Evidence
from .tools import LocalReadOnlyTools


class CustomerAgent:
    """Single-agent orchestration seam for the local, read-only demo."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.tools = LocalReadOnlyTools()
        self.policy = PolicyRetriever()

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
        if request.order_id is None:
            recorder.event("intent_classification", "skipped", {"reason": "order_id_required_for_ticket_02"})
            response = self._baseline_response(recorder.trace.trace_id)
            recorder.event("response_rendering", "completed")
            recorder.event("orchestration", "completed")
            return AgentResult(response=response, trace=recorder.finish(response))

        recorder.event("intent_classification", "completed", {"intent": "refund_eligibility", "confidence": 0.96})
        order_result = self.tools.get_order(request.user_id, request.order_id, recorder.trace.trace_id)
        recorder.event("tool_get_order", "completed" if order_result.status == "success" else "failed", {"status": order_result.status})
        if order_result.status != "success":
            response = CustomerResponse(
                intent="refund_eligibility",
                intent_confidence=0.96,
                eligibility="unknown",
                next_action="请确认订单号和登录账号；当前无法安全查询该订单，将为您转人工客服。",
                need_human=True,
                handoff_reason=f"订单查询失败：{order_result.status}",
                draft_for_human="用户希望咨询退款资格，但订单事实未能安全获取。",
                trace_id=recorder.trace.trace_id,
                answer="暂时无法判断该订单的退款资格。由于订单查询未成功，为保护您的信息，我将为您转人工客服。",
            )
            recorder.event("response_rendering", "completed")
            recorder.event("orchestration", "completed")
            return AgentResult(response=response, trace=recorder.finish(response))

        order = order_result.data
        logistics_result = self.tools.get_logistics(request.user_id, request.order_id, recorder.trace.trace_id)
        recorder.event("tool_get_logistics", "completed" if logistics_result.status == "success" else "failed", {"status": logistics_result.status})
        after_sales_result = self.tools.get_after_sales(request.user_id, request.order_id, recorder.trace.trace_id)
        recorder.event("tool_get_after_sales", "completed" if after_sales_result.status == "success" else "failed", {"status": after_sales_result.status})
        if logistics_result.status != "success" or after_sales_result.status != "success":
            response = CustomerResponse(
                intent="refund_eligibility", intent_confidence=0.96, eligibility="unknown",
                next_action="关键业务信息暂时不完整，请稍后重试或转人工客服。", need_human=True,
                handoff_reason="物流或售后信息查询失败", trace_id=recorder.trace.trace_id,
                answer="暂时无法判断该订单的退款资格。物流或售后信息不完整，我将为您转人工客服。",
            )
            recorder.event("response_rendering", "completed")
            recorder.event("orchestration", "completed")
            return AgentResult(response=response, trace=recorder.finish(response))

        policy_evidence = self.policy.search(request.message + " 退款")
        recorder.event("policy_retrieval", "completed", {"hits": len(policy_evidence), "policy_version": self.policy.policy_version})
        decision = decide_refund(order, logistics_result.data, after_sales_result.data)
        recorder.event("refund_decision", "completed", {"rule_id": decision.matched_rule_id, "eligibility": decision.eligibility})
        evidence = [
            Evidence(kind="order", summary=f"订单 {order['order_id']}：{order['payment_status']}、{order['order_status']}、{order['category']}"),
            Evidence(kind="logistics", summary=f"物流：{logistics_result.data['logistics_status']}，已签收={logistics_result.data['signed']}"),
            Evidence(kind="after_sales", summary=f"售后：进行中={after_sales_result.data['has_active_case']}"),
            *policy_evidence,
        ]
        is_human = decision.action in {"handoff", "draft_for_human"} or decision.eligibility == "unknown"
        action = "您可以点击“申请退款”生成待人工确认草稿。" if decision.action == "request_refund" else "系统会生成待人工确认的售后草稿。" if decision.action == "draft_for_human" else "请由人工客服继续核对。"
        response = CustomerResponse(
            intent="refund_eligibility", intent_confidence=0.96, eligibility=decision.eligibility,
            evidence=evidence, policy_version=decision.policy_version, next_action=action,
            need_human=is_human, handoff_reason=decision.reason if is_human else None,
            draft_for_human=f"订单 {order['order_id']}：{decision.reason}" if is_human else None,
            trace_id=recorder.trace.trace_id,
            answer=f"结论：{'符合退款资格' if decision.eligibility == 'eligible' else '不符合退款资格' if decision.eligibility == 'ineligible' else '暂时无法判断'}。依据：{decision.reason}（{decision.policy_version}）。下一步：{action}",
        )
        recorder.event("response_rendering", "completed")
        recorder.event("orchestration", "completed")
        return AgentResult(response=response, trace=recorder.finish(response))

    @staticmethod
    def _baseline_response(trace_id: str) -> CustomerResponse:
        return CustomerResponse(
            intent="unknown",
            intent_confidence=0.0,
            eligibility="unknown",
            next_action="请补充您要咨询的订单号；如果仍无法定位订单，我们会为您转人工客服。",
            need_human=False,
            trace_id=trace_id,
            answer=(
                "您好，我可以协助查询退款/退货问题。请先提供订单号，"
                "系统会根据订单、物流和售后信息给出判断。"
            ),
        )
