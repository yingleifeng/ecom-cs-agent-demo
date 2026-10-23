import time
from typing import Any, Callable

from .agents import FactsAgent, HandoffAgent, OrchestrationAgent, PolicyAgent
from .config import Settings
from .decision import decide_refund
from .observability import TraceRecorder
from .memory import LongTermMemoryStore
from .rag import PolicyRetriever
from .schemas import AgentResult, CustomerRequest, CustomerResponse, Evidence, OrderOption, ToolResult
from .session import InMemorySessionStore
from .tools import LocalReadOnlyTools, MCPReadOnlyTools


INTENT_CONFIDENCE_THRESHOLD = 0.85


class CustomerAgent:
    """Single-agent orchestration seam for the local, read-only demo."""

    def __init__(
        self,
        settings: Settings | None = None,
        session_store: InMemorySessionStore | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.tools: LocalReadOnlyTools | MCPReadOnlyTools = LocalReadOnlyTools()
        self._local_tools = self.tools
        self.policy = PolicyRetriever()
        self.sessions = session_store or InMemorySessionStore()
        self.memories = LongTermMemoryStore()
        self.orchestration_agent = OrchestrationAgent()
        self.policy_agent = PolicyAgent()
        self.facts_agent = FactsAgent()

    def handle(
        self,
        message: str,
        user_id: str,
        session_id: str,
        order_id: str | None = None,
        mode: str | None = None,
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
        request_started = time.perf_counter()
        agent_mode = request.mode or ("multi_agent" if self.settings.multi_agent_enabled else "single_agent")
        tool_mode = request.tool_mode or ("mcp" if self.settings.mcp_enabled else "local")
        if tool_mode == "mcp":
            self.tools = MCPReadOnlyTools(self.settings.request_timeout_seconds)
        elif isinstance(self.tools, MCPReadOnlyTools):
            self.tools = self._local_tools
        request = request.model_copy(update={"tool_mode": tool_mode, "mode": agent_mode})
        recorder = TraceRecorder(request.model_dump())
        if tool_mode == "mcp":
            recorder.event("tool_backend", "started", {"mode": tool_mode, "source": tool_mode, "latency_ms": 0.0})
            recorder.event("tool_backend", "completed", {"mode": tool_mode, "source": tool_mode, "latency_ms": 0.0, "connection_latency_ms": 0.0})
        session = self.sessions.get_or_create(request.session_id, request.user_id)
        slot_updates = session.observe(request.message, request.order_id)
        effective_order_id = session.current_order_id

        if agent_mode == "multi_agent":
            recorder.event("agent_orchestration", "started", {"role": "orchestration_agent"})
        intent, intent_confidence = self.orchestration_agent.classify(request.message, session.intent)
        if agent_mode == "multi_agent":
            recorder.event("agent_intent", "completed", {"role": "orchestration_agent", "intent": intent, "confidence": intent_confidence})
        session.intent = intent

        recorder.event("orchestration", "started", {"mode": request.mode, "tool_mode": tool_mode})
        recorder.event(
            "session_state",
            "completed",
            {"state": session.snapshot(), "slot_updates": slot_updates},
        )
        recorder.event(
            "intent_classification",
            "completed" if effective_order_id else "skipped",
            {"intent": intent, "confidence": intent_confidence},
        )

        memory_records = self.memories.list(request.user_id)
        memory_value = memory_records[0].value if memory_records else None
        preference_value, memory_reason = self.memories.extract_explicit_preference(request.message)
        memory_action = session.slots.get("memory_action")
        if preference_value:
            record = self.memories.write_preference(request.user_id, preference_value)
            recorder.event("long_term_memory_write", "completed", {"kind": record.kind, "value": record.value, "expires_at": record.expires_at.isoformat(), "reason": "explicit_user_consent"})
            memory_records = self.memories.list(request.user_id)
            memory_value = record.value
        elif "记住" in request.message or "记一下" in request.message:
            recorder.event("long_term_memory_write", "skipped", {"reason": memory_reason})
        if memory_action == "delete":
            removed = self.memories.delete(request.user_id)
            recorder.event("long_term_memory_delete", "completed", {"deleted_count": removed})
            memory_records = []
            memory_value = None
            session.slots.pop("memory_action", None)
        elif any(token in request.message for token in ("查看记忆", "我记住了什么", "查看长期记忆")):
            recorder.event("long_term_memory_read", "completed", {"record_count": len(memory_records), "reason": "user_requested_view"})
        elif memory_records and any(token in request.message for token in ("穿什么码", "尺码建议", "推荐尺码")):
            recorder.event("long_term_memory_read", "completed", {"record_count": 1, "kind": memory_records[0].kind, "adopted": True, "reason": "relevant_size_preference"})
        elif memory_records:
            recorder.event("long_term_memory_read", "skipped", {"record_count": len(memory_records), "reason": "not_relevant_to_current_request"})
        else:
            recorder.event("long_term_memory_read", "skipped", {"record_count": 0, "reason": "no_active_memory"})

        if session.status == "cancelled":
            return self._finish(
                recorder,
                self._terminal_response(
                    recorder.trace.trace_id,
                    intent,
                    intent_confidence,
                    slot_updates,
                    session.status,
                    "好的，已停止当前退款/售后处理，不会继续调用相关工具。",
                ),
            )

        if any(token in request.message for token in ("查看记忆", "我记住了什么", "查看长期记忆")):
            response = CustomerResponse(
                intent="unknown", next_action="您可以随时要求删除或更新这条偏好。", need_human=False,
                trace_id=recorder.trace.trace_id,
                answer=(f"当前保存的偏好：{memory_records[0].value}（90 天后过期）。" if memory_records else "当前没有保存的长期记忆。"),
            )
            return self._finish(recorder, response)
        if memory_action == "delete":
            response = CustomerResponse(
                intent="unknown", next_action="已停止使用并删除该记忆。", need_human=False,
                trace_id=recorder.trace.trace_id, answer="已删除您保存的长期记忆。",
            )
            return self._finish(recorder, response)
        if preference_value:
            response = CustomerResponse(
                intent="unknown", next_action="您可以随时查看或删除这条记忆。", need_human=False,
                trace_id=recorder.trace.trace_id, answer=f"好的，已记住您的尺码偏好：{preference_value}，90 天后自动过期。",
            )
            return self._finish(recorder, response)
        if memory_value and any(token in request.message for token in ("穿什么码", "尺码建议", "推荐尺码")):
            response = CustomerResponse(
                intent="unknown", next_action="这是基于您保存偏好的参考，具体尺码请以商品尺码表为准。", need_human=False,
                trace_id=recorder.trace.trace_id, answer=f"您之前保存的偏好是{memory_value}，可以作为选码参考。具体商品请以商品尺码表为准。",
            )
            return self._finish(recorder, response)

        if session.status == "closed":
            return self._finish(
                recorder,
                self._terminal_response(
                    recorder.trace.trace_id,
                    intent,
                    intent_confidence,
                    slot_updates,
                    session.status,
                    "好的，当前会话已结束。需要继续处理时，请重新发起会话。",
                ),
            )

        if session.status == "handoff_locked":
            return self._finish(
                recorder,
                CustomerResponse(
                    intent=intent,
                    intent_confidence=intent_confidence,
                    next_action="请等待人工客服继续处理。",
                    need_human=True,
                    handoff_reason="会话已转人工，机器人不再重复查询。",
                    session_state=session.status,
                    slot_updates=slot_updates,
                    trace_id=recorder.trace.trace_id,
                    answer="当前会话已转人工客服，我不会重复调用工具。请等待人工客服继续处理。",
                ),
            )

        if self._explicit_human_request(request.message):
            response = self._handoff_response(
                recorder.trace.trace_id,
                intent,
                intent_confidence,
                slot_updates,
                session.status,
                "用户明确要求人工客服",
                "好的，我将为您转接人工客服，请稍候。",
            )
            self._record_handoff(recorder, session, response.handoff_reason)
            response.session_state = session.status
            return self._finish(recorder, response)

        if self._has_business_dispute(request.message):
            response = self._handoff_response(
                recorder.trace.trace_id,
                intent,
                intent_confidence,
                slot_updates,
                session.status,
                "用户反馈金额争议或强烈投诉",
                "我已记录您的问题，将转人工客服核对订单和处理记录。",
            )
            self._record_handoff(recorder, session, response.handoff_reason)
            response.session_state = session.status
            return self._finish(recorder, response)

        if intent_confidence < INTENT_CONFIDENCE_THRESHOLD:
            session.intent_clarification_count += 1
            recorder.event(
                "intent_clarification",
                "started",
                {
                    "attempt": session.intent_clarification_count,
                    "threshold": INTENT_CONFIDENCE_THRESHOLD,
                    "confidence": intent_confidence,
                },
            )
            if session.intent_clarification_count >= 2:
                response = self._handoff_response(
                    recorder.trace.trace_id,
                    intent,
                    intent_confidence,
                    slot_updates,
                    session.status,
                    "连续两轮无法识别用户意图或置信度低于 0.85",
                    "我暂时无法判断您要咨询的具体问题，将为您转人工客服继续处理。",
                )
                self._record_handoff(recorder, session, response.handoff_reason)
                response.session_state = session.status
            else:
                response = self._clarification_response(
                    recorder.trace.trace_id,
                    intent,
                    intent_confidence,
                    slot_updates,
                    session.status,
                )
            recorder.event(
                "intent_clarification",
                "completed",
                {"need_human": response.need_human},
            )
            return self._finish(recorder, response)

        session.intent_clarification_count = 0

        if intent == "exchange_request":
            response = self._handoff_response(
                recorder.trace.trace_id,
                intent,
                intent_confidence,
                slot_updates,
                session.status,
                "当前版本不自动处理换货",
                "我已识别到您是想换货。当前版本不直接执行换货操作，我将为您转人工客服确认库存和处理方式。",
            )
            self._record_handoff(recorder, session, response.handoff_reason)
            response.session_state = session.status
            return self._finish(recorder, response)

        if intent == "policy_faq":
            return self._handle_policy_faq(
                request, recorder, session, intent, intent_confidence, slot_updates, request_started
            )

        if intent in {"refund_status", "logistics_issue"}:
            return self._handle_non_refund_flow(
                request,
                recorder,
                session,
                intent,
                intent_confidence,
                slot_updates,
                effective_order_id,
                request_started,
            )

        if effective_order_id is None:
            if session.status == "needs_order_id" or self._requires_order_id(request.message):
                if self._should_count_order_clarification(request.message, session):
                    session.mark_clarification()
                if session.clarification_count >= 3:
                    response = self._handoff_response(
                        recorder.trace.trace_id,
                        intent,
                        intent_confidence,
                        slot_updates,
                        session.status,
                        "连续多轮未获得可用订单号",
                        "我还无法定位到具体订单。为避免查错订单，我将为您转人工客服继续处理。",
                    )
                    self._record_handoff(recorder, session, response.handoff_reason)
                    response.session_state = session.status
                else:
                    options = session.order_options
                    if not options and self._should_list_recent_orders(
                        request.message,
                        session,
                    ):
                        recent_result = self._call_tool(
                            recorder,
                            "tool_list_recent_orders",
                            "list_recent_orders",
                            self.tools.list_recent_orders,
                            (request.user_id, recorder.trace.trace_id),
                            request.user_id,
                            "",
                            request_started,
                        )
                        options = (
                            recent_result.data.get("orders", [])
                            if recent_result.status == "success"
                            else []
                        )
                        session.set_order_options(options)
                    response = self._order_clarification_response(
                        recorder.trace.trace_id,
                        intent,
                        intent_confidence,
                        slot_updates,
                        session.status,
                        options,
                    )
            else:
                response = self._baseline_response(
                    recorder.trace.trace_id,
                    intent=intent,
                    intent_confidence=intent_confidence,
                    slot_updates=slot_updates,
                    session_state=session.status,
                )
                session.mark_unknown()
                response.session_state = session.status
            return self._finish(recorder, response)

        order_result = self._call_tool(
            recorder,
            "tool_get_order",
            "get_order",
            self.tools.get_order,
            (request.user_id, effective_order_id, recorder.trace.trace_id),
            request.user_id,
            effective_order_id,
            request_started,
        )
        if order_result.status != "success":
            response = self._handoff_response(
                recorder.trace.trace_id,
                intent,
                intent_confidence,
                slot_updates,
                session.status,
                f"订单查询失败：{order_result.status}",
                "暂时无法判断该订单的退款资格。由于订单查询未成功，为保护您的信息，我将为您转人工客服。",
                tools_called=["get_order"],
            )
            self._record_handoff(recorder, session, response.handoff_reason)
            response.session_state = session.status
            return self._finish(recorder, response)

        order = order_result.data
        logistics_result = self._call_tool(
            recorder,
            "tool_get_logistics",
            "get_logistics",
            self.tools.get_logistics,
            (request.user_id, effective_order_id, recorder.trace.trace_id),
            request.user_id,
            effective_order_id,
            request_started,
        )
        after_sales_result = self._call_tool(
            recorder,
            "tool_get_after_sales",
            "get_after_sales",
            self.tools.get_after_sales,
            (request.user_id, effective_order_id, recorder.trace.trace_id),
            request.user_id,
            effective_order_id,
            request_started,
        )

        if logistics_result.status != "success" or after_sales_result.status != "success":
            response = self._handoff_response(
                recorder.trace.trace_id,
                intent,
                intent_confidence,
                slot_updates,
                session.status,
                "物流或售后信息查询失败",
                "暂时无法判断该订单的退款资格。物流或售后信息不完整，我将为您转人工客服。",
                tools_called=["get_order", "get_logistics", "get_after_sales"],
            )
            self._record_handoff(recorder, session, response.handoff_reason)
            response.session_state = session.status
            return self._finish(recorder, response)

        missing_fields = self._missing_required_fields(order, logistics_result.data, after_sales_result.data)
        conflict = self._facts_conflict(order, logistics_result.data)
        if missing_fields or conflict:
            reason = (
                f"关键业务字段缺失：{', '.join(missing_fields)}"
                if missing_fields
                else "订单状态与物流事实冲突"
            )
            response = self._handoff_response(
                recorder.trace.trace_id,
                intent,
                intent_confidence,
                slot_updates,
                session.status,
                reason,
                "订单信息暂不完整或相互矛盾，无法安全判断退款资格，我将转人工客服核实。",
                tools_called=["get_order", "get_logistics", "get_after_sales"],
            )
            response.evidence = [
                Evidence(kind="order", summary=f"订单事实：{order}"),
                Evidence(kind="logistics", summary=f"物流事实：{logistics_result.data}"),
                Evidence(kind="after_sales", summary=f"售后事实：{after_sales_result.data}"),
            ]
            self._record_handoff(recorder, session, response.handoff_reason)
            response.session_state = session.status
            return self._finish(recorder, response)

        if self._request_timed_out(request_started):
            response = self._timeout_handoff(
                recorder, session, intent, intent_confidence, slot_updates, request_started
            )
            return self._finish(recorder, response)

        if agent_mode == "multi_agent":
            recorder.event("agent_policy", "started", {"role": "policy_agent"})
        policy_evidence = self.policy_agent.retrieve(self.policy, request.message + " 退款")
        if agent_mode == "multi_agent":
            recorder.event("agent_policy", "completed", {"role": "policy_agent", "hits": len(policy_evidence)})
        recorder.event(
            "policy_retrieval",
            "completed",
            {
                "tool": "retrieve_policy",
                "arguments": {"query": request.message + " 退款"},
                "status": "success",
                "hits": len(policy_evidence),
                "policy_version": self.policy.policy_version,
                "results": [
                    {
                        "snippet": item.summary,
                        "source": item.source,
                        "rank": item.rank,
                        "score": item.score,
                    }
                    for item in policy_evidence
                ],
            },
        )
        if self._request_timed_out(request_started):
            response = self._timeout_handoff(
                recorder, session, intent, intent_confidence, slot_updates, request_started
            )
            return self._finish(recorder, response)
        decision = decide_refund(order, logistics_result.data, after_sales_result.data)
        recorder.event(
            "refund_decision",
            "completed",
            {"rule_id": decision.matched_rule_id, "eligibility": decision.eligibility},
        )

        evidence = [
            Evidence(
                kind="order",
                summary=(
                    f"订单 {order['order_id']}：{order['payment_status']}、"
                    f"{order['order_status']}、{order['category']}"
                ),
            ),
            Evidence(
                kind="logistics",
                summary=(
                    f"物流：{logistics_result.data['logistics_status']}，"
                    f"已签收={logistics_result.data['signed']}"
                ),
            ),
            Evidence(
                kind="after_sales",
                summary=f"售后：进行中={after_sales_result.data['has_active_case']}",
            ),
            *policy_evidence,
        ]
        is_human = (
            decision.action in {"handoff", "draft_for_human"}
            or decision.eligibility == "unknown"
        )
        action = (
            "您可以点击“申请退款”生成待人工确认草稿。"
            if decision.action == "request_refund"
            else "系统会生成待人工确认的售后草稿。"
            if decision.action == "draft_for_human"
            else "请由人工客服继续核对。"
        )
        response = CustomerResponse(
            intent=intent,
            intent_confidence=intent_confidence,
            eligibility=decision.eligibility,
            session_state=session.status,
            slot_updates=slot_updates,
            tools_called=[
                "get_order",
                "get_logistics",
                "get_after_sales",
                "retrieve_policy",
            ],
            evidence=evidence,
            policy_version=decision.policy_version,
            next_action=action,
            need_human=is_human,
            handoff_reason=decision.reason if is_human else None,
            draft_for_human=(
                f"订单 {order['order_id']}：{decision.reason}" if is_human else None
            ),
            trace_id=recorder.trace.trace_id,
            answer=(
                f"您好！帮您查了一下，订单 {order['order_id']} 还没有发货，符合退款条件 😊 "
                f"稍后可以为您生成退款申请，经客服确认后即可处理~"
                if decision.eligibility == "eligible" and decision.action == "request_refund"
                else f"您好！已查询到订单 {order['order_id']}，商品已发出但您尚未签收，符合申请退款的条件 😊 "
                f"我会为您生成一份售后申请，需要客服进一步确认，请稍等~"
                if decision.eligibility == "eligible" and decision.action == "draft_for_human"
                else f"您好！很抱歉，该订单目前不符合退款条件。{decision.reason}，如有疑问欢迎联系人工客服进一步核实~"
                if decision.eligibility == "ineligible"
                else f"您好！您的订单情况需要人工客服进一步核实。{decision.reason}，帮您转接专属客服，请稍等 🙏"
            ),
        )
        if is_human:
            self._record_handoff(recorder, session, response.handoff_reason)
            response.session_state = session.status
        else:
            session.mark_resolved()
            response.session_state = session.status
        return self._finish(recorder, response)

    @staticmethod
    def _requires_order_id(message: str) -> bool:
        return any(
            token in message
            for token in (
                "订单",
                "退款",
                "退货",
                "物流",
                "发货",
                "签收",
                "售后",
                "换货",
                "没收到",
                "没到",
                "能退",
                "查",
                "继续退",
                "那单",
                "这单",
                "订单号",
                "截图",
                "帮我退",
            )
        )

    @staticmethod
    def _should_count_order_clarification(message: str, session: Any) -> bool:
        if session.clarification_count == 0:
            return True
        if session.awaiting_order_selection and (
            "还没发货" in message
            or "未发货" in message
            or "普通商品" in message
            or "已发货" in message
            or "定制" in message
            or "照片" in message
            or "凭证" in message
        ):
            return False
        return not any(
            token in message
            for token in ("还没发货", "未发货", "普通商品", "定制", "照片", "凭证", "已发货")
        )

    @staticmethod
    def _should_list_recent_orders(message: str, session: Any) -> bool:
        """Only expose order choices after an explicit, safe request for them."""
        if session.awaiting_order_selection:
            return True
        return any(
            token in message
            for token in ("最近订单", "最近那笔", "几笔订单", "几笔单", "订单列表", "列出最近")
        )

    @staticmethod
    def _explicit_human_request(message: str) -> bool:
        return any(token in message for token in ("找人工", "转人工", "人工客服", "别解释了"))

    @staticmethod
    def _has_business_dispute(message: str) -> bool:
        return any(
            token in message
            for token in ("黑我钱", "金额不对", "金额争议", "多扣钱", "少退钱", "投诉")
        )

    def _request_timed_out(self, request_started: float) -> bool:
        return time.perf_counter() - request_started >= self.settings.request_timeout_seconds

    def _timeout_handoff(
        self,
        recorder: TraceRecorder,
        session: Any,
        intent: str,
        intent_confidence: float,
        slot_updates: dict[str, Any],
        request_started: float,
    ) -> CustomerResponse:
        recorder.event(
            "request_timeout",
            "failed",
            {
                "timeout_seconds": self.settings.request_timeout_seconds,
                "elapsed_ms": round((time.perf_counter() - request_started) * 1000, 2),
            },
        )
        response = self._handoff_response(
            recorder.trace.trace_id,
            intent,
            intent_confidence,
            slot_updates,
            session.status,
            f"全链路超过 {self.settings.request_timeout_seconds:g} 秒时限",
            "处理超时，无法安全完成查询，我将转人工客服继续核实。",
        )
        self._record_handoff(recorder, session, response.handoff_reason)
        response.session_state = session.status
        return response

    @staticmethod
    def _missing_required_fields(
        order: dict[str, Any], logistics: dict[str, Any], after_sales: dict[str, Any]
    ) -> list[str]:
        requirements = {
            "order.payment_status": order,
            "order.order_status": order,
            "order.special_type": order,
            "logistics.logistics_status": logistics,
            "logistics.signed": logistics,
            "after_sales.has_active_case": after_sales,
            "after_sales.duplicate_request": after_sales,
        }
        return [key for key, values in requirements.items() if key.split(".", 1)[1] not in values]

    @staticmethod
    def _facts_conflict(order: dict[str, Any], logistics: dict[str, Any]) -> bool:
        order_status = order.get("order_status")
        logistics_status = logistics.get("logistics_status")
        signed = logistics.get("signed")
        return bool(
            (order_status == "unshipped" and (logistics_status != "not_shipped" or signed))
            or (order_status == "shipped" and logistics_status == "not_shipped")
            or (signed and logistics_status in {"not_shipped", "in_transit"})
        )

    @staticmethod
    def _clarification_response(
        trace_id: str,
        intent: str,
        intent_confidence: float,
        slot_updates: dict[str, Any],
        session_state: str,
    ) -> CustomerResponse:
        return CustomerResponse(
            intent=intent,
            intent_confidence=intent_confidence,
            eligibility="unknown",
            clarification_requested=True,
            slot_updates=slot_updates,
            session_state=session_state,
            next_action="请补充您要咨询的是退款资格、退款进度、物流异常还是换货问题。",
            trace_id=trace_id,
            answer="我还不确定您遇到的具体问题，能说得再具体一些吗？您是想查退款资格、退款进度、物流情况，还是申请换货呢~",
        )

    @staticmethod
    def _order_clarification_response(
        trace_id: str,
        intent: str,
        intent_confidence: float,
        slot_updates: dict[str, Any],
        session_state: str,
        options: list[dict[str, Any]],
    ) -> CustomerResponse:
        return CustomerResponse(
            intent=intent,
            intent_confidence=intent_confidence,
            eligibility="unknown",
            clarification_requested=True,
            slot_updates=slot_updates,
            session_state=session_state,
            order_options=[OrderOption.model_validate(option) for option in options],
            tools_called=["list_recent_orders"],
            next_action="请提供订单号，或回复“第一个”“第二个”“第三个”选择订单。",
            trace_id=trace_id,
            answer=(
                "为了不查错订单，麻烦先告诉我订单号，"
                "或者从您最近的订单中选一笔，我来帮您查~"
            ),
        )

    def _handle_policy_faq(
        self,
        request: CustomerRequest,
        recorder: TraceRecorder,
        session: Any,
        intent: str,
        intent_confidence: float,
        slot_updates: dict[str, Any],
        request_started: float,
    ) -> AgentResult:
        """直接用 RAG 检索知识库，回答政策类问题，不需要订单号。"""
        if request.mode == "multi_agent":
            recorder.event("agent_policy", "started", {"role": "policy_agent"})
        policy_evidence = self.policy_agent.retrieve(self.policy, request.message)
        if request.mode == "multi_agent":
            recorder.event("agent_policy", "completed", {"role": "policy_agent", "hits": len(policy_evidence)})
        self._record_policy(recorder, request.message, policy_evidence)

        if policy_evidence and policy_evidence[0].score > 0.05:
            top = policy_evidence[0]
            raw = top.summary.split("：", 1)[-1] if "：" in top.summary else top.summary
            content = self._strip_markdown(raw)
            answer = f"您好！{content} 如需了解更多或有具体订单问题，欢迎继续咨询~"
        else:
            answer = "您好！这个问题我暂时没有找到相关政策说明，建议您联系人工客服获取准确信息~"

        response = CustomerResponse(
            intent=intent,
            intent_confidence=intent_confidence,
            eligibility="unknown",
            slot_updates=slot_updates,
            session_state=session.status,
            tools_called=["retrieve_policy"],
            evidence=policy_evidence,
            policy_version=self.policy.policy_version,
            next_action="如有具体订单问题，请提供订单号，我来帮您查询。",
            need_human=False,
            trace_id=recorder.trace.trace_id,
            answer=answer,
        )
        return self._finish(recorder, response)

    def _handle_non_refund_flow(
        self,
        request: CustomerRequest,
        recorder: TraceRecorder,
        session: Any,
        intent: str,
        intent_confidence: float,
        slot_updates: dict[str, Any],
        effective_order_id: str | None,
        request_started: float,
    ) -> AgentResult:
        if effective_order_id is None:
            session.mark_clarification()
            if session.clarification_count >= 3:
                response = self._handoff_response(
                    recorder.trace.trace_id,
                    intent,
                    intent_confidence,
                    slot_updates,
                    session.status,
                    "连续多轮未获得可用订单号",
                    "我还无法定位到具体订单。为避免查错订单，我将为您转人工客服继续处理。",
                )
                self._record_handoff(recorder, session, response.handoff_reason)
                response.session_state = session.status
                return self._finish(recorder, response)

            options = session.order_options
            if not options and self._should_list_recent_orders(request.message, session):
                recent_result = self._call_tool(
                    recorder,
                    "tool_list_recent_orders",
                    "list_recent_orders",
                    self.tools.list_recent_orders,
                    (request.user_id, recorder.trace.trace_id),
                    request.user_id,
                    "",
                    request_started,
                )
                options = (
                    recent_result.data.get("orders", [])
                    if recent_result.status == "success"
                    else []
                )
                session.set_order_options(options)
            response = CustomerResponse(
                intent=intent,
                intent_confidence=intent_confidence,
                eligibility="unknown",
                clarification_requested=True,
                slot_updates=slot_updates,
                session_state=session.status,
                order_options=[OrderOption.model_validate(option) for option in options],
                tools_called=["list_recent_orders"],
                next_action="请补充订单号，我才能查询对应的订单信息。",
                trace_id=recorder.trace.trace_id,
                answer=(
                    "我已识别到您是在咨询退款进度。"
                    if intent == "refund_status"
                    else "我已识别到您是在咨询物流问题。"
                )
                + "请先提供订单号，或回复“第一个”“第二个”“第三个”选择订单，我再为您查询。",
            )
            return self._finish(recorder, response)

        if intent == "refund_status":
            after_sales_result = self._call_tool(
                recorder,
                "tool_get_after_sales",
                "get_after_sales",
                self.tools.get_after_sales,
                (request.user_id, effective_order_id, recorder.trace.trace_id),
                request.user_id,
                effective_order_id,
                request_started,
            )
            if request.mode == "multi_agent":
                recorder.event("agent_policy", "started", {"role": "policy_agent"})
            policy_evidence = self.policy_agent.retrieve(self.policy, request.message)
            if request.mode == "multi_agent":
                recorder.event("agent_policy", "completed", {"role": "policy_agent", "hits": len(policy_evidence)})
            self._record_policy(recorder, request.message, policy_evidence)
            response = self._handoff_response(
                recorder.trace.trace_id,
                intent,
                intent_confidence,
                slot_updates,
                session.status,
                "退款进度涉及资金状态，需要人工确认",
                "我已记录您的退款进度问题。当前查询结果需要人工客服进一步核对，我将为您转人工处理。",
                tools_called=["get_after_sales", "retrieve_policy"],
            )
        else:
            logistics_result = self._call_tool(
                recorder,
                "tool_get_logistics",
                "get_logistics",
                self.tools.get_logistics,
                (request.user_id, effective_order_id, recorder.trace.trace_id),
                request.user_id,
                effective_order_id,
                request_started,
            )
            response = self._handoff_response(
                recorder.trace.trace_id,
                intent,
                intent_confidence,
                slot_updates,
                session.status,
                "物流问题需要人工核实",
                "我已查询到您的物流问题。为避免对异常状态作出错误判断，将为您转人工客服继续核实。",
                tools_called=["get_logistics"],
            )
        self._record_handoff(recorder, session, response.handoff_reason)
        response.session_state = session.status
        return self._finish(recorder, response)

    def _record_policy(
        self,
        recorder: TraceRecorder,
        query: str,
        evidence: list[Evidence],
    ) -> None:
        recorder.event(
            "policy_retrieval",
            "completed",
            {
                "tool": "retrieve_policy",
                "arguments": {"query": query},
                "status": "success",
                "hits": len(evidence),
                "policy_version": evidence[0].policy_version if evidence else self.policy.policy_version,
                "results": [
                    {
                        "snippet": item.summary,
                        "source": item.source,
                        "rank": item.rank,
                        "score": item.score,
                    }
                    for item in evidence
                ],
            },
        )

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """将知识库 markdown 文本转成适合对话显示的纯文本。"""
        import re
        # 去掉标题符号
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # 去掉加粗/斜体
        text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
        lines = []
        header_cells: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            # 跳过表格分隔行（|---|）
            if re.match(r"^\|[-: |]+\|$", stripped):
                continue
            if stripped.startswith("|") and stripped.endswith("|"):
                cells = [c.strip() for c in stripped.strip("|").split("|") if c.strip()]
                if not header_cells:
                    # 第一行是表头，暂存
                    header_cells = cells
                else:
                    # 数据行：key: value 格式（取第1、2列）
                    if len(cells) >= 2:
                        lines.append(f"- {cells[0]}：{cells[1]}")
                    else:
                        lines.append(f"- {'、'.join(cells)}")
            elif stripped:
                header_cells = []  # 表格结束，重置
                lines.append(stripped)
        result = "\n".join(lines)
        result = re.sub(r"\n{3,}", "\n\n", result).strip()
        return result

    @staticmethod
    def _eligibility_text(value: str) -> str:
        return {
            "eligible": "符合退款资格",
            "ineligible": "不符合退款资格",
            "unknown": "暂时无法判断",
        }[value]

    def _call_tool(
        self,
        recorder: TraceRecorder,
        event_name: str,
        tool_name: str,
        operation: Callable[..., ToolResult],
        arguments: tuple[Any, ...],
        user_id: str,
        order_id: str,
        request_started: float,
    ) -> ToolResult:
        """Call a read tool and retry transient failures once within the request budget."""
        multi_agent = recorder.trace.request.get("mode") == "multi_agent"
        if multi_agent:
            recorder.event("agent_facts", "started", {"role": "facts_agent", "tool": tool_name})
        result: ToolResult
        for attempt in range(2):
            if time.perf_counter() - request_started >= self.settings.request_timeout_seconds:
                result = ToolResult(
                    status="timeout",
                    error_code="REQUEST_TIMEOUT",
                    error_message="请求总耗时达到上限，已停止后续工具调用",
                )
            else:
                try:
                    result = self.facts_agent.query(operation, *arguments) if multi_agent else operation(*arguments)
                except (TimeoutError, ConnectionError, OSError) as exc:
                    result = ToolResult(
                        status="timeout" if isinstance(exc, TimeoutError) else "upstream_error",
                        error_code=type(exc).__name__.upper(),
                        error_message="只读工具调用失败",
                    )
                if time.perf_counter() - request_started >= self.settings.request_timeout_seconds:
                    result = ToolResult(
                        status="timeout",
                        error_code="REQUEST_TIMEOUT",
                        error_message="请求总耗时达到上限，已停止后续工具调用",
                        latency_ms=result.latency_ms,
                        source=result.source,
                    )

            detail = {
                "tool": tool_name,
                "arguments": {"user_id": user_id, "order_id": order_id},
                "status": result.status,
                "error_code": result.error_code,
                "error_message": result.error_message,
                "result_data": result.data,
                "source": result.source,
                "latency_ms": result.latency_ms,
                "attempt": attempt + 1,
                "retrying": result.status in {"timeout", "upstream_error"} and attempt == 0,
            }
            recorder.event(
                event_name,
                "completed" if result.status == "success" else "failed",
                detail,
            )
            if result.status not in {"timeout", "upstream_error"} or attempt == 1:
                break
        if multi_agent:
            recorder.event(
                "agent_facts", "completed" if result.status == "success" else "failed",
                {"role": "facts_agent", "tool": tool_name, "status": result.status},
            )
        return result

    @staticmethod
    def _handoff_summary(recorder: TraceRecorder, response: CustomerResponse) -> str:
        request = recorder.trace.request
        events = recorder.trace.events
        session_event = next((event for event in events if event.name == "session_state"), None)
        state = (session_event.detail.get("state", {}) if session_event else {})
        slots = state.get("slots", {})
        facts: list[str] = []
        policy_version = response.policy_version
        for event in events:
            detail = event.detail
            if event.name.startswith("tool_"):
                data = detail.get("result_data", {})
                if data:
                    facts.append(f"{detail.get('tool')}={data}")
            if event.name == "policy_retrieval":
                policy_version = policy_version or detail.get("policy_version")
        return "\n".join(
            [
                f"用户原话：{request.get('message', '')}",
                f"用户/订单：{request.get('user_id', '')} / {state.get('current_order_id') or request.get('order_id') or slots.get('order_id') or '未定位'}",
                f"意图：{response.intent}（置信度 {response.intent_confidence:.2f}）",
                f"会话槽位与追问：{slots}；订单追问 {state.get('clarification_count', 0)} 次；意图澄清 {state.get('intent_clarification_count', 0)} 次",
                f"订单/物流/售后事实：{'；'.join(facts) if facts else '未获取'}",
                f"政策版本：{policy_version or '未检索'}",
                f"失败或转人工原因：{response.handoff_reason or '未说明'}",
                f"建议动作：{response.next_action}",
            ]
        )

    @staticmethod
    def _record_tool(
        recorder: TraceRecorder,
        event_name: str,
        tool_name: str,
        result: Any,
        user_id: str,
        order_id: str,
    ) -> None:
        recorder.event(
            event_name,
            "completed" if result.status == "success" else "failed",
            {
                "tool": tool_name,
                "arguments": {"user_id": user_id, "order_id": order_id},
                "status": result.status,
                "error_code": result.error_code,
                "error_message": result.error_message,
                "result_data": result.data,
                "source": result.source,
                "latency_ms": result.latency_ms,
            },
        )

    @staticmethod
    def _record_handoff(recorder: TraceRecorder, session: Any, reason: str | None) -> None:
        session.mark_handoff()
        recorder.event("handoff", "completed", {"reason": reason or "未说明"})

    @staticmethod
    def _finish(recorder: TraceRecorder, response: CustomerResponse) -> AgentResult:
        multi_agent = recorder.trace.request.get("mode") == "multi_agent"
        if response.need_human:
            if multi_agent:
                recorder.event("agent_handoff", "started", {"role": "handoff_agent"})
            response.draft_for_human = HandoffAgent.summarize(
                lambda: CustomerAgent._handoff_summary(recorder, response)
            )
            if multi_agent:
                recorder.event("agent_handoff", "completed", {"role": "handoff_agent"})
        recorder.event("response_rendering", "completed")
        if multi_agent:
            recorder.event(
                "agent_orchestration", "completed",
                {
                    "role": "orchestration_agent",
                    "result": {
                        "intent": response.intent,
                        "eligibility": response.eligibility,
                        "need_human": response.need_human,
                    },
                    "agent_invocations": sum(
                        event.name.startswith("agent_") and event.status == "started"
                        for event in recorder.trace.events
                    ),
                    "token_usage": 0,
                    "estimated_cost_usd": 0.0,
                    "cost_note": "mock agents; no model tokens or API cost",
                },
            )
        recorder.event("orchestration", "completed")
        trace = recorder.finish(response)
        return AgentResult(response=trace.response or response, trace=trace)

    @staticmethod
    def _baseline_response(
        trace_id: str,
        *,
        intent: str = "unknown",
        intent_confidence: float = 0.0,
        slot_updates: dict[str, Any] | None = None,
        session_state: str = "active",
    ) -> CustomerResponse:
        return CustomerResponse(
            intent=intent,
            intent_confidence=intent_confidence,
            eligibility="unknown",
            slot_updates=slot_updates or {},
            session_state=session_state,
            next_action="请补充您要咨询的订单号；如果仍无法定位订单，我们会为您转人工客服。",
            need_human=False,
            trace_id=trace_id,
            answer=(
                "您好！我是售后客服助手，主要协助处理退款、退货、物流查询和换货问题。"
                "您这个问题超出了我的服务范围，建议您联系人工客服或查看帮助中心~"
            ),
        )

    @staticmethod
    def _handoff_response(
        trace_id: str,
        intent: str,
        intent_confidence: float,
        slot_updates: dict[str, Any],
        session_state: str,
        reason: str,
        answer: str,
        *,
        tools_called: list[str] | None = None,
    ) -> CustomerResponse:
        return CustomerResponse(
            intent=intent,
            intent_confidence=intent_confidence,
            eligibility="unknown",
            next_action="请由人工客服继续核对。",
            need_human=True,
            handoff_reason=reason,
            draft_for_human="用户请求未能在当前自动化范围内安全完成，需要人工继续处理。",
            session_state=session_state,
            slot_updates=slot_updates,
            tools_called=tools_called or [],
            trace_id=trace_id,
            answer=answer,
        )

    @staticmethod
    def _terminal_response(
        trace_id: str,
        intent: str,
        intent_confidence: float,
        slot_updates: dict[str, Any],
        session_state: str,
        answer: str,
    ) -> CustomerResponse:
        return CustomerResponse(
            intent=intent,
            intent_confidence=intent_confidence,
            next_action="无需继续调用工具。",
            session_state=session_state,
            slot_updates=slot_updates,
            trace_id=trace_id,
            answer=answer,
        )
