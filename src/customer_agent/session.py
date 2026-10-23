import re
from dataclasses import dataclass, field
from threading import RLock
from typing import Any


ORDER_ID_PATTERN = re.compile(r"\b(?:o_\d+|\d{8,})\b", re.IGNORECASE)

TERMINAL_STATES = {"cancelled", "closed", "handoff_locked"}


@dataclass
class SessionState:
    """Minimal in-memory state for one active customer conversation."""

    session_id: str
    user_id: str
    turn_count: int = 0
    intent: str = "unknown"
    current_order_id: str | None = None
    previous_order_id: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    order_options: list[dict[str, Any]] = field(default_factory=list)
    awaiting_order_selection: bool = False
    clarification_count: int = 0
    intent_clarification_count: int = 0
    status: str = "active"
    messages: list[dict[str, str]] = field(default_factory=list)

    def observe(self, message: str, explicit_order_id: str | None = None) -> dict[str, Any]:
        """Record a turn and return only the slot changes from this turn."""
        self.turn_count += 1
        self.messages.append({"role": "user", "content": message})
        self.messages = self.messages[-10:]

        updates: dict[str, Any] = {}
        if self.status == "handoff":
            self.status = "handoff_locked"
            return updates
        if self.status in {"cancelled", "closed", "handoff_locked"}:
            return updates

        if is_expired_marker(message):
            self.expire()

        order_ids = extract_order_ids(message)
        order_id = explicit_order_id.lower() if explicit_order_id else (order_ids[0] if order_ids else None)
        if order_id is None:
            selected_order_id = select_order_from_message(message, self.order_options)
            if selected_order_id:
                order_id = selected_order_id
                updates["order_id"] = selected_order_id
                updates["selection"] = selected_order_id
                self.clear_order_options()
        if order_id:
            if self.current_order_id and order_id != self.current_order_id:
                self.previous_order_id = self.current_order_id
            self.current_order_id = order_id
            self.slots["order_id"] = order_id
            updates["order_id"] = order_id
            if self.status == "needs_order_id":
                self.status = "active"
            if len(order_ids) > 1:
                self.slots["secondary_order_id"] = order_ids[1]
                updates["secondary_order_id"] = order_ids[1]
        elif self.current_order_id and refers_to_previous_order(message) and self.previous_order_id:
            self.current_order_id, self.previous_order_id = (
                self.previous_order_id,
                self.current_order_id,
            )
            self.slots["order_id"] = self.current_order_id
            updates["active_order_id"] = self.current_order_id

        self._extract_common_slots(message, updates)

        if contains_cancel(message):
            self.status = "cancelled"
            self.slots["task"] = "cancelled"
            updates["task"] = "cancelled"
        elif contains_goodbye(message):
            self.status = "closed"
            self.slots["task"] = "closed"
            updates["task"] = "closed"

        return updates

    def mark_clarification(self) -> None:
        self.clarification_count += 1
        self.status = "needs_order_id"

    def set_order_options(self, options: list[dict[str, Any]]) -> None:
        self.order_options = options
        self.awaiting_order_selection = bool(options)

    def clear_order_options(self) -> None:
        self.order_options = []
        self.awaiting_order_selection = False

    def mark_handoff(self) -> None:
        self.status = "handoff"

    def mark_active(self) -> None:
        if self.status not in TERMINAL_STATES and self.status != "handoff":
            self.status = "active"

    def mark_resolved(self) -> None:
        if self.status == "active":
            self.status = "resolved"

    def mark_unknown(self) -> None:
        if self.status in {"active", "resolved"}:
            self.status = "unknown"

    def expire(self) -> None:
        """Drop temporary conversation slots while retaining the session identity."""
        self.current_order_id = None
        self.previous_order_id = None
        self.slots.clear()
        self.clear_order_options()
        self.status = "needs_order_id"
        self.clarification_count = 1

    def _extract_common_slots(self, message: str, updates: dict[str, Any]) -> None:
        if "还没发货" in message or "未发货" in message:
            self.slots["order_status"] = "unshipped"
            updates["order_status"] = "unshipped"
        elif "已发货" in message or "发货了" in message:
            self.slots["order_status"] = "shipped"
            updates["order_status"] = "shipped"

        if "普通商品" in message:
            self.slots["special_type"] = None
            updates["special_type"] = None
        elif "定制" in message:
            self.slots["special_type"] = "custom"
            updates["special_type"] = "custom"

        if any(token in message for token in ("照片", "截图", "凭证")):
            self.slots["evidence"] = "photo"
            updates["evidence"] = "photo"
        if "微信" in message:
            self.slots["payment_method"] = "wechat"
            updates["payment_method"] = "wechat"
        if "换小一码" in message:
            self.slots["target_size"] = "小一码"
            updates["target_size"] = "小一码"
        elif "换大一码" in message:
            self.slots["target_size"] = "大一码"
            updates["target_size"] = "大一码"
        if "麂皮" in message or "鸡皮" in message:
            self.slots["product"] = "麂皮鞋"
            updates["product"] = "麂皮鞋"
        if "上次" in message and "M 码" in message and "偏大" in message:
            value = "size_preference:M偏大"
            self.slots["memory_candidate"] = value
            updates["memory_candidate"] = value
        elif "平时穿 M 码" in message:
            value = "size:M"
            self.slots["memory_candidate"] = value
            updates["memory_candidate"] = value
        if "删掉" in message or "删除" in message:
            self.slots["memory_action"] = "delete"
            updates["memory_action"] = "delete"

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "turn_count": self.turn_count,
            "intent": self.intent,
            "current_order_id": self.current_order_id,
            "previous_order_id": self.previous_order_id,
            "slots": dict(self.slots),
            "clarification_count": self.clarification_count,
            "intent_clarification_count": self.intent_clarification_count,
            "status": self.status,
            "order_options": list(self.order_options),
            "awaiting_order_selection": self.awaiting_order_selection,
        }


class InMemorySessionStore:
    """Process-local store; deliberately replaceable by a persistent adapter later."""

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], SessionState] = {}
        self._lock = RLock()

    def get_or_create(self, session_id: str, user_id: str) -> SessionState:
        key = (user_id, session_id)
        with self._lock:
            if key not in self._sessions:
                self._sessions[key] = SessionState(session_id=session_id, user_id=user_id)
            return self._sessions[key]

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def expire(self, session_id: str, user_id: str) -> None:
        self.get_or_create(session_id, user_id).expire()


def extract_order_id(message: str) -> str | None:
    order_ids = extract_order_ids(message)
    return order_ids[0] if order_ids else None


def extract_order_ids(message: str) -> list[str]:
    return list(dict.fromkeys(match.group(0).lower() for match in ORDER_ID_PATTERN.finditer(message)))


def select_order_from_message(
    message: str,
    options: list[dict[str, Any]],
) -> str | None:
    if not options:
        return None
    normalized = message.strip()
    ordinal_tokens = {
        0: ("第一个", "第一单"),
        1: ("第二个", "第二单"),
        2: ("第三个", "第三单"),
    }
    for index, tokens in ordinal_tokens.items():
        if index < len(options) and any(
            normalized == token
            or normalized.startswith(token)
            or f"选{token}" in normalized
            for token in tokens
        ):
            return options[index]["order_id"]
    return None


def refers_to_previous_order(message: str) -> bool:
    return any(token in message for token in ("回到刚才", "刚才那单", "之前那单"))


def is_expired_marker(message: str) -> bool:
    return "会话超过 TTL" in message or "会话超时" in message


def contains_cancel(message: str) -> bool:
    text = message.strip()
    return (
        text.startswith(("不退了", "不用查了", "不要查了", "取消", "先不"))
        or "算了" in text
    )


def contains_goodbye(message: str) -> bool:
    return any(token in message for token in ("再见", "拜拜", "不用了，谢谢", "好的谢谢"))


def classify_intent(message: str, previous: str = "unknown") -> tuple[str, float]:
    """Small deterministic baseline classifier used before a model is introduced."""
    if contains_cancel(message):
        return previous if previous in {"refund_request", "refund_eligibility"} else "unknown", 0.96
    if contains_goodbye(message):
        return "unknown", 0.96
    if "人工" in message:
        return "unknown", 0.99
    if any(token in message for token in ("退款进度", "退款怎么", "退款没到账", "处理中", "被拒")):
        return "refund_status", 0.9
    if "黑我钱" in message or "我的钱" in message:
        return "refund_status", 0.9
    if any(
        token in message
        for token in (
            "几笔订单",
            "几笔单",
            "最近的",
            "最近订单",
            "最近那笔",
            "哪一单",
            "继续退",
            "刚才那单",
        )
    ):
        return "refund_eligibility", 0.86
    if previous == "refund_eligibility" and any(
        token in message
        for token in (
            "还没发货",
            "未发货",
            "普通商品",
            "已发货",
            "签收",
            "订单号",
            "这单",
            "那单",
        )
    ):
        return previous, 0.86
    if previous in {
        "refund_eligibility",
        "refund_request",
        "exchange_request",
        "refund_status",
        "logistics_issue",
    } and extract_order_ids(message):
        return previous, 0.86
    if previous == "refund_eligibility" and any(
        token in message for token in ("不知道订单号", "不记得订单号", "没有订单号")
    ):
        return previous, 0.86
    if previous == "refund_eligibility" and message.strip() in {
        "第一个",
        "第一单",
        "第二个",
        "第二单",
        "第三个",
        "第三单",
    }:
        return previous, 0.86
    if any(token in message for token in ("换货", "换小", "换大", "换颜色")):
        if "退款" in message and previous == "exchange_request":
            return "refund_request", 0.9
        return "exchange_request", 0.9
    # policy_faq 必须在 refund_eligibility / logistics_issue 之前判断：
    # 纯政策问法（"怎么算""多久""规则"等）不含订单号，应走 RAG 而非工具调用
    _faq_signals = ("怎么算", "规定", "规则", "政策", "时效", "几天", "无理由",
                    "发票", "包邮", "运费谁", "怎么开", "到账", "多久才")
    _order_signals = ("帮我退", "我要退", "申请退款", "发起退款", "订单", "o_",
                      "能退", "可以退", "坏了", "损坏", "没收到", "没到")
    if any(sig in message for sig in _faq_signals) and not any(sig in message for sig in _order_signals):
        return "policy_faq", 0.88
    if any(token in message for token in ("退款", "退货", "能退", "可以退", "不要了", "坏了", "损坏")):
        if any(token in message for token in ("帮我退", "我要退", "申请退款", "发起退款")):
            return "refund_request", 0.9
        return "refund_eligibility", 0.9
    if any(token in message for token in ("物流", "到哪", "没收到", "没到", "签收", "发货")):
        return "logistics_issue", 0.86
    if any(token in message for token in ("开发票", "报销", "增值税", "普通发票")):
        return "policy_faq", 0.82
    return previous if previous != "unknown" and message.strip() else "unknown", 0.0
