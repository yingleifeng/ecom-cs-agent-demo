from fastapi import FastAPI

from .orchestrator import CustomerAgent
from .schemas import AgentResult, CustomerRequest

app = FastAPI(title="E-commerce Customer Agent Demo", version="0.1.0")
agent = CustomerAgent()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=AgentResult)
def chat(request: CustomerRequest) -> AgentResult:
    return agent.handle_request(request)
