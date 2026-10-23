import json
import time
from pathlib import Path
from typing import Any

from ..schemas import ToolResult


class LocalReadOnlyTools:
    """Deterministic read-only adapters over the demo JSON data."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path(__file__).resolve().parents[3] / "data"
        self.orders = self._load("orders.json")
        self.logistics = self._load("logistics.json")
        self.after_sales = self._load("after_sales.json")

    def _load(self, filename: str) -> list[dict[str, Any]]:
        return json.loads((self.data_dir / filename).read_text(encoding="utf-8"))

    def _result(self, status: str, data: dict[str, Any] | None = None, **kwargs: Any) -> ToolResult:
        return ToolResult(status=status, data=data or {}, latency_ms=round((time.perf_counter() % 1) * 3, 2), **kwargs)

    def _validate(self, user_id: str, order_id: str | None) -> ToolResult | None:
        if not user_id or (order_id is not None and not order_id):
            return self._result("invalid_argument", error_code="INVALID_ARGUMENT")
        return None

    def get_order(self, user_id: str, order_id: str | None, request_id: str) -> ToolResult:
        invalid = self._validate(user_id, order_id)
        if invalid:
            return invalid
        if order_id is None:
            return self.list_recent_orders(user_id, request_id)
        return self._authorized_order(user_id, order_id)

    def _authorized_order(self, user_id: str, order_id: str) -> ToolResult:
        matches = [item for item in self.orders if item["order_id"] == order_id]
        if not matches:
            return self._result("not_found", error_code="ORDER_NOT_FOUND")
        order = matches[0]
        if order["user_id"] != user_id:
            return self._result("forbidden", error_code="ORDER_FORBIDDEN")
        return self._result("success", order)

    def list_recent_orders(self, user_id: str, request_id: str) -> ToolResult:
        """Return only safe summary fields for orders owned by the current user."""
        if not user_id:
            return self._result("invalid_argument", error_code="INVALID_ARGUMENT")
        recent = [item for item in self.orders if item["user_id"] == user_id][:3]
        return self._result(
            "success",
            {"orders": [self._redact_order(item) for item in recent]},
        )

    def get_logistics(self, user_id: str, order_id: str | None, request_id: str) -> ToolResult:
        invalid = self._validate(user_id, order_id)
        if invalid:
            return invalid
        if order_id is None:
            return self._result("invalid_argument", error_code="ORDER_REQUIRED")
        order_result = self._authorized_order(user_id, order_id)
        if order_result.status != "success":
            return order_result
        matches = [item for item in self.logistics if item["order_id"] == order_id]
        return self._result("success", matches[0]) if matches else self._result("data_incomplete", error_code="LOGISTICS_MISSING")

    def get_after_sales(self, user_id: str, order_id: str | None, request_id: str) -> ToolResult:
        invalid = self._validate(user_id, order_id)
        if invalid:
            return invalid
        if order_id is None:
            return self._result("invalid_argument", error_code="ORDER_REQUIRED")
        order_result = self._authorized_order(user_id, order_id)
        if order_result.status != "success":
            return order_result
        matches = [item for item in self.after_sales if item["order_id"] == order_id]
        return self._result("success", matches[0]) if matches else self._result("data_incomplete", error_code="AFTER_SALES_MISSING")

    @staticmethod
    def _redact_order(order: dict[str, Any]) -> dict[str, Any]:
        return {key: order[key] for key in ("order_id", "product_name", "order_status", "ordered_at")}
