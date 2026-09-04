"""Streamlit UI placeholder for the later interactive demo.

The ticket-01 baseline is intentionally runnable through the FastAPI API and CLI first.
"""

from customer_agent.orchestrator import CustomerAgent


def main() -> None:
    agent = CustomerAgent()
    result = agent.handle(
        message="我想问一下订单能不能退",
        user_id="u_001",
        session_id="demo-session",
    )
    print(result.model_dump_json(indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
