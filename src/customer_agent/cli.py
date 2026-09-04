import argparse

from .orchestrator import CustomerAgent
from .schemas import CustomerRequest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one customer-agent request")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--session-id", default="cli-session")
    parser.add_argument("--order-id")
    parser.add_argument("--message", required=True)
    args = parser.parse_args()
    result = CustomerAgent().handle_request(
        CustomerRequest(
            message=args.message,
            user_id=args.user_id,
            session_id=args.session_id,
            order_id=args.order_id,
        )
    )
    print(result.model_dump_json(indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
