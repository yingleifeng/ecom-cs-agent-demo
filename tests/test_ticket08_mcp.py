from customer_agent.config import Settings
from customer_agent.orchestrator import CustomerAgent
from customer_agent.schemas import CustomerRequest
from customer_agent.tools import LocalReadOnlyTools, MCPReadOnlyTools


def _request(mode: str | None = None) -> CustomerRequest:
    return CustomerRequest(
        message="订单还没发货，可以退款吗？",
        user_id="u_001",
        session_id=f"ticket08-{mode or 'env'}",
        order_id="o_1001",
        tool_mode=mode,
    )


def test_mcp_tools_match_local_data_and_preserve_authorization() -> None:
    local = LocalReadOnlyTools()
    mcp = MCPReadOnlyTools()
    for name in ("get_order", "get_logistics", "get_after_sales"):
        expected = getattr(local, name)("u_001", "o_1001", "test")
        actual = getattr(mcp, name)("u_001", "o_1001", "test")
        assert actual.status == expected.status == "success"
        assert actual.data == expected.data
        assert actual.source == "mcp"
    denied = mcp.get_order("u_001", "o_2001", "test")
    assert denied.status == "forbidden"
    assert denied.data == {}


def test_orchestrator_selects_mcp_and_records_backend_and_call_timings() -> None:
    result = CustomerAgent(Settings(mcp_enabled=False)).handle_request(_request("mcp"))
    assert result.response.eligibility == "eligible"
    assert result.response.need_human is False
    events = result.trace.events
    assert any(event.name == "tool_backend" and event.detail.get("mode") == "mcp" for event in events)
    calls = [event for event in events if event.name in {"tool_get_order", "tool_get_logistics", "tool_get_after_sales"}]
    assert [event.detail["source"] for event in calls] == ["mcp"] * 3
    assert all(event.detail["latency_ms"] >= 0 for event in calls)


def test_mcp_enabled_environment_default_and_explicit_local_override(monkeypatch) -> None:
    monkeypatch.setenv("MCP_ENABLED", "true")
    agent = CustomerAgent(Settings.from_env())
    mcp_result = agent.handle_request(_request())
    assert mcp_result.trace.request["tool_mode"] == "mcp"
    local_result = agent.handle_request(_request("local"))
    assert local_result.trace.request["tool_mode"] == "local"
    assert local_result.response.eligibility == "eligible"
