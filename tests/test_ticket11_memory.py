from datetime import datetime, timedelta, timezone

from customer_agent.memory import LongTermMemoryStore
from customer_agent.orchestrator import CustomerAgent
from customer_agent.schemas import CustomerRequest


def _request(message: str, session: str) -> CustomerRequest:
    return CustomerRequest(message=message, user_id="u_001", session_id=session)


def test_ticket11_explicit_opt_in_recalls_across_sessions_and_can_be_deleted() -> None:
    agent = CustomerAgent()
    saved = agent.handle_request(_request("我上次穿 M 码偏大，记住一下", "memory-save"))
    assert "已记住" in saved.response.answer
    assert any(event.name == "long_term_memory_write" and event.status == "completed" for event in saved.trace.events)

    recalled = agent.handle_request(_request("这次这件穿什么码？", "memory-new-session"))
    assert "M码偏大" in recalled.response.answer
    assert any(event.name == "long_term_memory_read" and event.detail.get("adopted") for event in recalled.trace.events)

    viewed = agent.handle_request(_request("查看长期记忆", "memory-view"))
    assert "M码偏大" in viewed.response.answer
    deleted = agent.handle_request(_request("把刚才记住的删掉", "memory-delete"))
    assert "已删除" in deleted.response.answer
    assert agent.memories.list("u_001") == []


def test_ticket11_memory_is_user_scoped_and_sensitive_information_is_rejected() -> None:
    store = LongTermMemoryStore()
    assert store.extract_explicit_preference("我平时穿 M 码") == (None, "not_explicitly_requested")
    assert store.extract_explicit_preference("记住我的银行卡 6222000011112222，我穿 M 码") == (None, "sensitive_content_rejected")
    value, reason = store.extract_explicit_preference("记住我平时穿 M 码")
    assert (value, reason) == ("M码", "accepted")
    store.write_preference("u_001", value)
    assert store.recall_preference("u_001") is not None
    assert store.recall_preference("u_002") is None


def test_ticket11_expired_memory_is_not_recalled() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store = LongTermMemoryStore(clock=lambda: now)
    store.write_preference("u_001", "M码偏大")
    now += timedelta(days=91)
    assert store.recall_preference("u_001") is None


def test_ticket11_memory_does_not_replace_live_order_facts_or_refund_rules() -> None:
    agent = CustomerAgent()
    agent.memories.write_preference("u_001", "M码偏大")
    result = agent.handle_request(CustomerRequest(
        message="订单 o_1001 还没发货，可以退款吗？", user_id="u_001",
        session_id="memory-not-refund", order_id="o_1001",
    ))
    assert result.response.eligibility == "eligible"
    assert result.response.tools_called[:3] == ["get_order", "get_logistics", "get_after_sales"]
    events = {event.name for event in result.trace.events}
    assert "tool_get_order" in events and "tool_get_logistics" in events and "tool_get_after_sales" in events
    assert any(event.name == "long_term_memory_read" and event.detail["reason"] == "not_relevant_to_current_request" for event in result.trace.events)
