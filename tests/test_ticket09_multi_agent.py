from customer_agent.config import Settings
from customer_agent.orchestrator import CustomerAgent
from customer_agent.schemas import CustomerRequest
from evals.compare_agent_modes import compare_dataset


def _request(mode=None, session="ticket09"):
    return CustomerRequest(
        message="订单还没发货，可以退款吗？",
        user_id="u_001",
        session_id=session,
        order_id="o_1001",
        mode=mode,
    )


def test_multi_agent_environment_default_and_explicit_mode_override():
    enabled = CustomerAgent(Settings(multi_agent_enabled=True))
    result = enabled.handle_request(_request())
    assert result.trace.request["mode"] == "multi_agent"
    assert result.response.eligibility == "eligible"
    assert {event.name for event in result.trace.events} >= {
        "agent_orchestration", "agent_intent", "agent_policy", "agent_facts"
    }

    explicit_single = enabled.handle_request(_request("single_agent", "ticket09-single"))
    assert explicit_single.trace.request["mode"] == "single_agent"
    assert not any(event.name.startswith("agent_") for event in explicit_single.trace.events)


def test_single_and_multi_agent_share_result_and_tool_contracts():
    single = CustomerAgent(Settings(multi_agent_enabled=False)).handle_request(
        _request("single_agent", "ticket09-compare-single")
    )
    multi = CustomerAgent(Settings(multi_agent_enabled=False)).handle_request(
        _request("multi_agent", "ticket09-compare-multi")
    )
    assert single.response.eligibility == multi.response.eligibility
    assert single.response.intent == multi.response.intent
    assert single.response.need_human == multi.response.need_human
    assert [event.detail.get("tool") for event in single.trace.events if event.name.startswith("tool_")] == [
        event.detail.get("tool") for event in multi.trace.events if event.name.startswith("tool_")
    ]
    assert all(event.detail.get("source") == "mock_data" for event in multi.trace.events if event.name.startswith("tool_"))


def test_multi_agent_mode_comparison_reports_consistency_cost_and_localization():
    dataset = {
        "dataset_id": "ticket09-small",
        "version": "1",
        "cases": [{
            "case_id": "eligible-order",
            "user_id": "u_001",
            "turns": [{"user": "订单还没发货，可以退款吗？", "order_id": "o_1001"}],
        }],
    }
    report = compare_dataset(dataset)
    assert report["comparison"]["paired_turns"] == 1
    assert report["comparison"]["result_consistency"] == 1.0
    assert report["comparison"]["token_usage"] == {"single_agent": 0, "multi_agent": 0}
    assert report["comparison"]["estimated_model_cost_usd"]["multi_agent"] == 0.0
