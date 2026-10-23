"""Small, privacy-bounded long-term memory store for simulated demo users."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from threading import RLock
from typing import Callable


TTL = timedelta(days=90)
_PREFERENCE = re.compile(r"(?:上次|平时|通常).{0,8}(?:穿|买)?\s*(XS|S|M|L|XL|XXL)\s*码?.{0,8}(偏大|偏小|合适)?", re.IGNORECASE)
_SENSITIVE = re.compile(r"1\d{10}|\b\d{16,19}\b|身份证|银行卡|验证码|密码|支付", re.IGNORECASE)


@dataclass(frozen=True)
class MemoryRecord:
    kind: str
    value: str
    created_at: datetime
    expires_at: datetime

    def public(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value, "created_at": self.created_at.isoformat(), "expires_at": self.expires_at.isoformat()}


class LongTermMemoryStore:
    """Process-local mock store. Data is isolated by injected user_id."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._records: dict[str, list[MemoryRecord]] = {}
        self._lock = RLock()

    @staticmethod
    def extract_explicit_preference(message: str) -> tuple[str | None, str]:
        if "记住" not in message and "记一下" not in message:
            return None, "not_explicitly_requested"
        if _SENSITIVE.search(message):
            return None, "sensitive_content_rejected"
        match = _PREFERENCE.search(message)
        if not match:
            return None, "unsupported_memory_type"
        size, fit = match.groups()
        if fit is None:
            context = message[match.start():match.end() + 8]
            fit = next((candidate for candidate in ("偏大", "偏小", "合适") if candidate in context), None)
        value = f"{size.upper()}码" + (f"{fit}" if fit else "")
        return value, "accepted"

    def write_preference(self, user_id: str, value: str) -> MemoryRecord:
        now = self._clock()
        record = MemoryRecord("size_preference", value, now, now + TTL)
        with self._lock:
            self._purge(user_id, now)
            records = [item for item in self._records.get(user_id, []) if item.kind != record.kind]
            records.append(record)
            self._records[user_id] = records
        return record

    def list(self, user_id: str) -> list[MemoryRecord]:
        with self._lock:
            self._purge(user_id, self._clock())
            return list(self._records.get(user_id, []))

    def recall_preference(self, user_id: str) -> MemoryRecord | None:
        return next((item for item in self.list(user_id) if item.kind == "size_preference"), None)

    def delete(self, user_id: str) -> int:
        with self._lock:
            self._purge(user_id, self._clock())
            removed = len(self._records.pop(user_id, []))
            return removed

    def _purge(self, user_id: str, now: datetime) -> None:
        active = [item for item in self._records.get(user_id, []) if item.expires_at > now]
        if active:
            self._records[user_id] = active
        else:
            self._records.pop(user_id, None)
