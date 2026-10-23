"""MCP stdio client exposing the same ToolResult interface as local tools."""
import json
import os
import subprocess
import sys
import time
from typing import Any

from ..schemas import ToolResult


class MCPReadOnlyTools:
    def __init__(self, timeout_seconds: float = 3.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.command = os.getenv("MCP_SERVER_COMMAND")

    def _call(self, name: str, user_id: str, order_id: str | None, request_id: str) -> ToolResult:
        started = time.perf_counter()
        args = {"user_id": user_id, "order_id": order_id, "request_id": request_id}
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "customer-agent-demo", "version": "1.0.0"}}}
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        invoke = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": args}}
        command = self.command.split() if self.command else [sys.executable, "-m", "customer_agent.tools.mcp_server"]
        env = os.environ.copy()
        src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        try:
            process = subprocess.run(command, input="\n".join(map(json.dumps, (initialize, initialized, invoke))) + "\n", text=True, capture_output=True, timeout=self.timeout_seconds, env=env, check=False)
            lines = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
            payload = next((item for item in lines if item.get("id") == 2), None)
            if process.returncode or payload is None or "error" in payload:
                return ToolResult(status="upstream_error", error_code="MCP_UPSTREAM_ERROR", error_message=(process.stderr or "Invalid MCP response")[:300], latency_ms=round((time.perf_counter() - started) * 1000, 2), source="mcp")
            result = payload.get("result", {})
            content = next((item.get("text") for item in result.get("content", []) if item.get("type") == "text"), None)
            if not content:
                raise ValueError("MCP response has no tool result")
            decoded: dict[str, Any] = json.loads(content)
            decoded["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            decoded["source"] = "mcp"
            return ToolResult.model_validate(decoded)
        except subprocess.TimeoutExpired:
            return ToolResult(status="timeout", error_code="MCP_TIMEOUT", latency_ms=round((time.perf_counter() - started) * 1000, 2), source="mcp")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return ToolResult(status="upstream_error", error_code="MCP_UPSTREAM_ERROR", error_message=str(exc)[:300], latency_ms=round((time.perf_counter() - started) * 1000, 2), source="mcp")

    def get_order(self, user_id: str, order_id: str | None, request_id: str) -> ToolResult:
        return self._call("get_order", user_id, order_id, request_id)

    def get_logistics(self, user_id: str, order_id: str | None, request_id: str) -> ToolResult:
        return self._call("get_logistics", user_id, order_id, request_id)

    def get_after_sales(self, user_id: str, order_id: str | None, request_id: str) -> ToolResult:
        return self._call("get_after_sales", user_id, order_id, request_id)

    def list_recent_orders(self, user_id: str, request_id: str) -> ToolResult:
        result = self.get_order(user_id, None, request_id)
        if result.status == "success" and "orders" not in result.data:
            result.data = {"orders": []}
        return result
