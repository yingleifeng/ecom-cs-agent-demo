import json
from pathlib import Path
from unittest.mock import Mock

from customer_agent.orchestrator import CustomerAgent
from customer_agent.schemas import CustomerRequest, ToolResult
from customer_agent.config import Settings
from evals.metrics import exact_tool_path, score_turn
from evals.runner import load_dataset, run_dataset


DATASET = Path(__file__).parents[1] / "data" / "multiturn_eval_v1.json"


def test_session_handoff_locks_only_on_next_turn() -> None:
    agent = CustomerAgent()
    first = agent.handle_request(
        CustomerRequest(
            message="订单 o_1002 已发货但还没收到，能退吗？",
            user_id="u_001",
            session_id="handoff-test",
        )
    )
    assert first.response.need_human is True
    assert first.response.session_state == "handoff"

    second = agent.handle_request(
        CustomerRequest(
            message="那你再帮我查一次",
            user_id="u_001",
            session_id="handoff-test",
        )
    )
    assert second.response.need_human is True
    assert second.response.session_state == "handoff_locked"
    assert "get_order" not in second.response.tools_called


def test_trace_contains_ordered_tool_names() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="订单 o_1001 能退款吗",
            user_id="u_001",
            session_id="trace-test",
        )
    )
    assert exact_tool_path(result.trace.model_dump(mode="json")) == [
        "get_order",
        "get_logistics",
        "get_after_sales",
        "retrieve_policy",
    ]


def test_eval_checks_expected_tool_failure_status() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="订单 o_1001 能退款吗",
            user_id="u_001",
            session_id="tool-status-test",
        )
    )
    scored = score_turn(
        {
            "intent": "refund_eligibility",
            "slot_updates": {"order_id": "o_1001"},
            "tools": ["get_order:timeout"],
            "handoff": True,
        },
        result.response.model_dump(mode="json"),
        result.trace.model_dump(mode="json"),
    )
    assert scored["actual_tool_statuses"][0] == "success"
    assert scored["tool_match"] is False


def test_eval_runner_replays_all_cases() -> None:
    dataset = load_dataset(DATASET)
    report = run_dataset(dataset)
    assert report["summary"]["case_count"] == 40
    assert report["summary"]["turn_count"] == 79
    assert report["summary"]["unsupported_turns"] == 5
    assert report["failures"]
    json.dumps(report, ensure_ascii=False)


def test_ticket_03_exchange_is_identified_and_handed_off_without_refund_decision() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="鞋子买大了，订单 o_1002 能换小一码吗",
            user_id="u_001",
            session_id="ticket-03-exchange",
        )
    )
    assert result.response.intent == "exchange_request"
    assert result.response.intent_confidence >= 0.85
    assert result.response.need_human is True
    assert result.response.tools_called == []
    assert "refund_decision" not in {event.name for event in result.trace.events}


def test_ticket_03_refund_status_uses_after_sales_only() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="退款怎么还没到账，订单 o_1001",
            user_id="u_001",
            session_id="ticket-03-refund-status",
        )
    )
    assert result.response.intent == "refund_status"
    assert result.response.need_human is True
    assert result.response.tools_called == ["get_after_sales", "retrieve_policy"]
    assert exact_tool_path(result.trace.model_dump(mode="json")) == [
        "get_after_sales",
        "retrieve_policy",
    ]


def test_ticket_03_logistics_issue_uses_logistics_only() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="o_1002 到哪了",
            user_id="u_001",
            session_id="ticket-03-logistics",
        )
    )
    assert result.response.intent == "logistics_issue"
    assert result.response.need_human is True
    assert result.response.tools_called == ["get_logistics"]
    assert "refund_decision" not in {event.name for event in result.trace.events}


def test_ticket_03_unknown_request_is_clarified_then_handed_off() -> None:
    agent = CustomerAgent()
    first = agent.handle_request(
        CustomerRequest(
            message="你们家老板是谁",
            user_id="u_001",
            session_id="ticket-03-unknown",
        )
    )
    assert first.response.intent == "unknown"
    assert first.response.clarification_requested is True
    assert first.response.need_human is False

    second = agent.handle_request(
        CustomerRequest(
            message="我也不知道，随便问问",
            user_id="u_001",
            session_id="ticket-03-unknown",
        )
    )
    assert second.response.intent == "unknown"
    assert second.response.need_human is True
    assert "连续两轮无法识别" in (second.response.handoff_reason or "")


def test_ticket_03_low_confidence_intent_is_clarified_then_handed_off() -> None:
    agent = CustomerAgent()
    first = agent.handle_request(
        CustomerRequest(
            message="订单 o_1001 能退款吗",
            user_id="u_001",
            session_id="ticket-03-low-confidence",
        )
    )
    assert first.response.intent_confidence >= 0.85

    clarification = agent.handle_request(
        CustomerRequest(
            message="嗯",
            user_id="u_001",
            session_id="ticket-03-low-confidence",
        )
    )
    assert clarification.response.intent == "refund_eligibility"
    assert clarification.response.intent_confidence < 0.85
    assert clarification.response.clarification_requested is True
    assert clarification.response.need_human is False
    assert clarification.response.tools_called == []
    assert "refund_decision" not in {
        event.name for event in clarification.trace.events
    }

    handoff = agent.handle_request(
        CustomerRequest(
            message="还是不太明白",
            user_id="u_001",
            session_id="ticket-03-low-confidence",
        )
    )
    assert handoff.response.intent_confidence < 0.85
    assert handoff.response.need_human is True
    assert handoff.response.session_state == "handoff"
    assert "置信度低于 0.85" in (handoff.response.handoff_reason or "")
    assert handoff.response.tools_called == []
    assert "refund_decision" not in {event.name for event in handoff.trace.events}


def test_ticket_03_confident_intent_resets_low_confidence_clarification_count() -> None:
    agent = CustomerAgent()
    agent.handle_request(
        CustomerRequest(
            message="你们家老板是谁",
            user_id="u_001",
            session_id="ticket-03-confidence-reset",
        )
    )
    assert agent.sessions.get_or_create(
        "ticket-03-confidence-reset", "u_001"
    ).intent_clarification_count == 1

    agent.handle_request(
        CustomerRequest(
            message="订单 o_1001 能退款吗",
            user_id="u_001",
            session_id="ticket-03-confidence-reset",
        )
    )
    assert agent.sessions.get_or_create(
        "ticket-03-confidence-reset", "u_001"
    ).intent_clarification_count == 0


def test_ticket_05_retries_transient_tool_failure_once() -> None:
    agent = CustomerAgent()
    original = agent.tools.get_order
    attempts = 0

    def flaky_order(*args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return ToolResult(status="upstream_error", error_code="TEMPORARY")
        return original(*args)

    agent.tools.get_order = Mock(side_effect=flaky_order)
    agent.tools.get_logistics = Mock(
        return_value=ToolResult(
            status="success",
            data={"logistics_status": "not_shipped", "signed": False},
        )
    )
    agent.tools.get_after_sales = Mock(
        return_value=ToolResult(
            status="success",
            data={"has_active_case": False, "duplicate_request": False},
        )
    )
    result = agent.handle_request(
        CustomerRequest(
            message="订单 o_1001 能退款吗",
            user_id="u_001",
            session_id="ticket-05-retry",
        )
    )
    attempts = [event.detail for event in result.trace.events if event.name == "tool_get_order"]
    assert [attempt["status"] for attempt in attempts] == ["upstream_error", "success"]
    assert attempts[0]["retrying"] is True
    assert result.response.eligibility == "eligible"


def test_ticket_05_second_transient_failure_hands_off_without_eligibility() -> None:
    agent = CustomerAgent()
    agent.tools.get_order = Mock(
        side_effect=[
            ToolResult(status="timeout", error_code="TIMEOUT"),
            ToolResult(status="timeout", error_code="TIMEOUT"),
        ]
    )
    agent.tools.get_logistics = Mock()
    agent.tools.get_after_sales = Mock()
    result = agent.handle_request(
        CustomerRequest(
            message="订单 o_1001 能退款吗",
            user_id="u_001",
            session_id="ticket-05-retry-fails",
        )
    )
    assert agent.tools.get_logistics.call_count == 0
    assert result.response.eligibility == "unknown"
    assert result.response.need_human is True
    assert "timeout" in (result.response.handoff_reason or "")


def test_ticket_05_handoff_summary_contains_context_and_retrieved_facts() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="订单 o_1002 已发货但还没收到，能退吗？",
            user_id="u_001",
            session_id="ticket-05-summary",
        )
    )
    summary = result.response.draft_for_human or ""
    assert "用户原话：订单 o_1002 已发货但还没收到，能退吗？" in summary
    assert "意图：refund_eligibility" in summary
    assert "get_order=" in summary
    assert "policy_v1.0" in summary
    assert "建议动作：" in summary


def test_ticket_05_special_goods_and_amount_dispute_handoff() -> None:
    special = CustomerAgent().handle_request(
        CustomerRequest(
            message="订单 o_1003 能退款吗",
            user_id="u_001",
            session_id="ticket-05-special",
        )
    )
    assert special.response.eligibility == "unknown"
    assert special.response.need_human is True

    dispute = CustomerAgent().handle_request(
        CustomerRequest(
            message="你们是不是黑我钱，金额不对",
            user_id="u_001",
            session_id="ticket-05-dispute",
        )
    )
    assert dispute.response.need_human is True
    assert "争议" in (dispute.response.handoff_reason or "")
    assert dispute.response.tools_called == []


def test_ticket_05_denied_order_never_produces_eligibility_conclusion() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="查一下订单 o_2001 能不能退",
            user_id="u_001",
            session_id="ticket-05-forbidden",
        )
    )
    assert result.response.eligibility == "unknown"
    assert result.response.need_human is True
    assert "forbidden" in (result.response.handoff_reason or "")
    assert "refund_decision" not in {event.name for event in result.trace.events}


def test_ticket_05_every_order_scoped_read_checks_user_ownership() -> None:
    from customer_agent.tools import LocalReadOnlyTools

    tools = LocalReadOnlyTools()
    for name in ("get_order", "get_logistics", "get_after_sales"):
        result = getattr(tools, name)("u_001", "o_2001", "ticket-05-auth")
        assert result.status == "forbidden"
        assert result.data == {}


def test_ticket_05_active_or_duplicate_after_sales_forces_unknown_handoff() -> None:
    agent = CustomerAgent()
    agent.tools.after_sales[0]["has_active_case"] = True
    result = agent.handle_request(
        CustomerRequest(
            message="订单 o_1001 能退款吗",
            user_id="u_001",
            session_id="ticket-05-active-after-sales",
        )
    )
    assert result.response.eligibility == "unknown"
    assert result.response.need_human is True
    assert "进行中的售后或重复申请" in (result.response.handoff_reason or "")
    agent.tools.after_sales[0]["has_active_case"] = False


def test_ticket_05_required_fact_missing_or_conflicting_stops_decision() -> None:
    missing_agent = CustomerAgent()
    missing_agent.tools.get_after_sales = lambda *args: ToolResult(
        status="success", data={"has_active_case": False}
    )
    missing = missing_agent.handle_request(
        CustomerRequest(
            message="订单 o_1001 能退款吗",
            user_id="u_001",
            session_id="ticket-05-missing-facts",
        )
    )
    assert missing.response.eligibility == "unknown"
    assert missing.response.need_human is True
    assert "duplicate_request" in (missing.response.handoff_reason or "")
    conflict_agent = CustomerAgent()
    conflict_agent.tools.get_logistics = lambda *args: ToolResult(
        status="success", data={"logistics_status": "in_transit", "signed": False}
    )
    conflict = conflict_agent.handle_request(
        CustomerRequest(
            message="订单 o_1001 能退款吗",
            user_id="u_001",
            session_id="ticket-05-conflict",
        )
    )
    assert conflict.response.eligibility == "unknown"
    assert conflict.response.need_human is True
    assert "冲突" in (conflict.response.handoff_reason or "")


def test_ticket_05_total_request_timeout_stops_later_tool_calls() -> None:
    agent = CustomerAgent(settings=Settings(request_timeout_seconds=0.03))
    original = agent.tools.get_order

    def slow_order(*args):
        import time

        time.sleep(0.05)
        return original(*args)

    agent.tools.get_order = slow_order
    result = agent.handle_request(
        CustomerRequest(
            message="订单 o_1001 能退款吗",
            user_id="u_001",
            session_id="ticket-05-timeout",
        )
    )
    assert result.response.need_human is True
    assert "get_logistics" not in result.response.tools_called
    assert [event.detail["status"] for event in result.trace.events if event.name == "tool_get_order"] == ["timeout", "timeout"]


def test_ticket_05_total_timeout_during_policy_retrieval_hands_off() -> None:
    import time

    agent = CustomerAgent(settings=Settings(request_timeout_seconds=0.03))
    original_search = agent.policy.search

    def slow_search(query):
        time.sleep(0.05)
        return original_search(query)

    agent.policy.search = slow_search
    result = agent.handle_request(
        CustomerRequest(
            message="订单 o_1001 能退款吗",
            user_id="u_001",
            session_id="ticket-05-policy-timeout",
        )
    )
    assert result.response.eligibility == "unknown"
    assert result.response.need_human is True
    assert "全链路超过" in (result.response.handoff_reason or "")
    assert "refund_decision" not in {event.name for event in result.trace.events}


def test_ticket_04_missing_order_lists_recent_redacted_orders() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="我有几笔订单，查最近那笔",
            user_id="u_001",
            session_id="ticket-04-recent-orders",
        )
    )
    assert result.response.clarification_requested is True
    assert result.response.need_human is False
    assert [item.order_id for item in result.response.order_options] == [
        "o_1001",
        "o_1002",
        "o_1003",
    ]
    assert all("user_id" not in item.model_dump() for item in result.response.order_options)
    assert result.response.tools_called == ["list_recent_orders"]


def test_ticket_04_selecting_recent_order_continues_refund_flow() -> None:
    agent = CustomerAgent()
    first = agent.handle_request(
        CustomerRequest(
            message="我有几笔订单，查最近那笔",
            user_id="u_001",
            session_id="ticket-04-select",
        )
    )
    assert first.response.order_options

    second = agent.handle_request(
        CustomerRequest(
            message="第二个",
            user_id="u_001",
            session_id="ticket-04-select",
        )
    )
    assert second.response.slot_updates["order_id"] == "o_1002"
    assert second.response.intent == "refund_eligibility"
    assert second.response.tools_called == [
        "get_order",
        "get_logistics",
        "get_after_sales",
        "retrieve_policy",
    ]
    assert second.response.eligibility == "eligible"
    assert second.response.order_options == []


def test_ticket_04_current_order_reference_uses_session_memory() -> None:
    agent = CustomerAgent()
    agent.handle_request(
        CustomerRequest(
            message="订单 o_1001 能退款吗",
            user_id="u_001",
            session_id="ticket-04-reference",
        )
    )
    result = agent.handle_request(
        CustomerRequest(
            message="这单是什么状态",
            user_id="u_001",
            session_id="ticket-04-reference",
        )
    )
    assert result.response.slot_updates == {}
    assert result.response.tools_called[0] == "get_order"
    order_event = next(event for event in result.trace.events if event.name == "tool_get_order")
    assert order_event.detail["arguments"]["order_id"] == "o_1001"


def test_ticket_04_recent_orders_respect_system_user_id() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="我有几笔订单，列出最近的",
            user_id="u_002",
            session_id="ticket-04-user-boundary",
        )
    )
    assert [item.order_id for item in result.response.order_options] == ["o_2001"]
    assert all(item.order_id != "o_1001" for item in result.response.order_options)
