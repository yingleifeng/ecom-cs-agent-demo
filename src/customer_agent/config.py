from dataclasses import dataclass
import os


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    model_provider: str = "mock"
    model_name: str = "mock"
    mcp_enabled: bool = False
    multi_agent_enabled: bool = False
    request_timeout_seconds: float = 8.0

    @classmethod
    def from_env(cls) -> "Settings":
        raw_timeout = os.getenv("REQUEST_TIMEOUT_SECONDS", "8")
        try:
            timeout = float(raw_timeout)
        except ValueError:
            timeout = 8.0
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            model_provider=os.getenv("MODEL_PROVIDER", "mock"),
            model_name=os.getenv("MODEL_NAME", "mock"),
            mcp_enabled=_as_bool(os.getenv("MCP_ENABLED")),
            multi_agent_enabled=_as_bool(os.getenv("MULTI_AGENT_ENABLED")),
            request_timeout_seconds=timeout,
        )
