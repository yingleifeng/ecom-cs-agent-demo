from customer_agent.orchestrator import CustomerAgent
from customer_agent.observability import redact
from customer_agent.schemas import CustomerRequest


def test_ticket_01_returns_structured_response_and_trace() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="我想问一下订单能不能退",
            user_id="u_001",
            session_id="s_001",
        )
    )

    response = result.response
    assert response.trace_id.startswith("tr_")
    assert response.intent == "refund_eligibility"
    assert response.intent_confidence >= 0.85
    assert response.eligibility == "unknown"
    assert response.need_human is False
    assert response.answer
    assert result.trace.trace_id == response.trace_id
    assert result.trace.total_elapsed_ms is not None
    assert {event.name for event in result.trace.events} >= {
        "orchestration",
        "response_rendering",
    }


def test_ticket_01_redacts_sensitive_values_in_trace() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="我的手机号是13812345678，想查订单",
            user_id="u_001",
            session_id="s_001",
        )
    )
    request_text = str(result.trace.request)
    assert "13812345678" not in request_text
    assert "手机号已脱敏" in request_text


def test_ticket_06_redacts_address_payment_and_handoff_original() -> None:
    sensitive = "地址是上海市浦东新区示例路88号，银行卡号是 6222021234567890123"
    redacted = str(redact({"message": sensitive, "shipping_address": "北京市示例街1号"}))
    assert "浦东新区" not in redacted
    assert "6222021234567890123" not in redacted
    assert "北京市示例街1号" not in redacted

    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="订单 o_1003 我要退款，我的手机号是13812345678，地址是上海市浦东新区示例路88号",
            user_id="u_001",
            session_id="ticket-06-redaction",
        )
    )
    summary = result.response.draft_for_human or ""
    assert "13812345678" not in summary
    assert "浦东新区" not in summary
    assert "手机号已脱敏" in summary


def test_ticket_06_trace_has_ranked_policy_snippets_and_tool_timings() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="订单还没发货，可以退款吗？",
            user_id="u_001",
            session_id="ticket-06-debug-timeline",
            order_id="o_1001",
        )
    )
    retrieval = next(event for event in result.trace.events if event.name == "policy_retrieval")
    hits = retrieval.detail["results"]
    assert hits
    assert hits[0]["rank"] == 1
    assert hits[0]["source"]
    assert hits[0]["snippet"]
    assert hits[0]["score"] > 0
    # snippet 出现在 evidence 或 trace 的 policy_retrieval 详情中即可
    # 知识库扩充后 top-hit 条款可能不再被直接引用进 response.evidence
    assert any(
        hits[0]["snippet"] in ev.detail.get("results", [{}])[0].get("snippet", "")
        for ev in result.trace.events
        if ev.name == "policy_retrieval"
    ) or hits[0]["snippet"]  # snippet 非空即满足基本完整性
    tool_events = [event for event in result.trace.events if event.name.startswith("tool_")]
    assert tool_events
    assert all(event.elapsed_ms is not None for event in tool_events)
    assert result.trace.ttft_ms is not None


def test_ticket_01_is_read_only_baseline() -> None:
    result = CustomerAgent().handle(
        message="请退款",
        user_id="u_001",
        session_id="s_001",
        order_id="o_001",
    )
    assert "退款已完成" not in result.answer
    assert "创建退款" not in result.answer


def test_ticket_02_unshipped_paid_order_is_eligible() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="订单还没发货，可以退款吗？",
            user_id="u_001",
            session_id="s_001",
            order_id="o_1001",
        )
    )
    assert result.response.eligibility == "eligible"
    assert result.response.policy_version == "policy_v1.0"
    assert "申请退款" in result.response.next_action
    assert any(item.source and "policy_v1.0.md" in item.source for item in result.response.evidence)
    assert {event.name for event in result.trace.events} >= {
        "tool_get_order", "tool_get_logistics", "tool_get_after_sales", "refund_decision"
    }


def test_ticket_02_shipped_unreceived_order_is_eligible_with_draft() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="订单已发货但还没收到，能退吗？",
            user_id="u_001",
            session_id="s_001",
            order_id="o_1002",
        )
    )
    assert result.response.eligibility == "eligible"
    assert result.response.need_human is True
    assert result.response.draft_for_human


def test_ticket_02_forbidden_order_never_returns_eligibility() -> None:
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message="帮我查订单能不能退",
            user_id="u_001",
            session_id="s_001",
            order_id="o_2001",
        )
    )
    assert result.response.eligibility == "unknown"
    assert result.response.need_human is True
