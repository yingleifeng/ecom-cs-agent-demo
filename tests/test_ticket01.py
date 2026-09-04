from customer_agent.orchestrator import CustomerAgent
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
    assert response.intent == "unknown"
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


def test_ticket_01_is_read_only_baseline() -> None:
    result = CustomerAgent().handle(
        message="请退款",
        user_id="u_001",
        session_id="s_001",
        order_id="o_001",
    )
    assert "退款已完成" not in result.answer
    assert "创建退款" not in result.answer
