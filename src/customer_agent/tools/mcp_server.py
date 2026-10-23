"""Minimal stdio MCP server for the demo's three read-only tools.

This implements the MCP JSON-RPC lifecycle without an SDK dependency so the
demo remains runnable in an offline environment.
"""
import json
import sys
from typing import Any

from .local import LocalReadOnlyTools


TOOLS = [
    {"name": "get_order", "description": "Read an order owned by the user", "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string"}, "order_id": {"type": ["string", "null"]}, "request_id": {"type": "string"}}, "required": ["user_id", "order_id", "request_id"]}},
    {"name": "get_logistics", "description": "Read logistics for an owned order", "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string"}, "order_id": {"type": ["string", "null"]}, "request_id": {"type": "string"}}, "required": ["user_id", "order_id", "request_id"]}},
    {"name": "get_after_sales", "description": "Read after-sales information for an owned order", "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string"}, "order_id": {"type": ["string", "null"]}, "request_id": {"type": "string"}}, "required": ["user_id", "order_id", "request_id"]}},
]


def dispatch(message: dict[str, Any], tools: LocalReadOnlyTools) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "customer-readonly-tools", "version": "1.0.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})
        method_impl = {"get_order": tools.get_order, "get_logistics": tools.get_logistics, "get_after_sales": tools.get_after_sales}.get(name)
        if method_impl is None:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "unknown tool"}}
        outcome = method_impl(**arguments)
        result = {"content": [{"type": "text", "text": outcome.model_dump_json()}], "isError": outcome.status != "success"}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> None:
    tools = LocalReadOnlyTools()
    for line in sys.stdin:
        try:
            message = json.loads(line)
            response = dispatch(message, tools)
        except Exception as exc:  # Return protocol errors; never write business data.
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
