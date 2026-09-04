from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from .orchestrator import CustomerAgent
from .schemas import AgentResult, CustomerRequest

app = FastAPI(title="E-commerce Customer Agent Demo", version="0.1.0")
agent = CustomerAgent()
DEMO_HTML = Path(__file__).resolve().parents[2] / "demo.html"


@app.get("/", include_in_schema=False)
def demo_page() -> FileResponse:
    return FileResponse(DEMO_HTML, media_type="text/html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=AgentResult)
def chat(request: CustomerRequest) -> AgentResult:
    return agent.handle_request(request)
