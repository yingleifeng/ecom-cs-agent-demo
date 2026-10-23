from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from evals.runner import run_ticket07_dataset
from evals.ticket07 import validate as validate_ticket07_dataset

from .orchestrator import CustomerAgent
from .schemas import AgentResult, CustomerRequest

app = FastAPI(title="E-commerce Customer Agent Demo", version="0.1.0")
agent = CustomerAgent()
DEMO_HTML = Path(__file__).resolve().parents[2] / "demo.html"
TICKET07_DATASET = DEMO_HTML.parent / "data" / "ticket07_eval_v1.json"
TICKET10_REPORT = DEMO_HTML.parent / "reports" / "ticket10_demo_eval.json"


@app.get("/", include_in_schema=False)
def demo_page() -> FileResponse:
    return FileResponse(DEMO_HTML, media_type="text/html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=AgentResult)
def chat(request: CustomerRequest) -> AgentResult:
    return agent.handle_request(request)


@app.post("/evaluate/ticket07")
def evaluate_ticket07() -> dict:
    """Run the fixed 60-case acceptance set from the local demo environment."""
    import json

    from evals.runner import load_dataset

    dataset = load_dataset(TICKET07_DATASET)
    validate_ticket07_dataset(dataset)
    report = run_ticket07_dataset(dataset)
    repeated = run_ticket07_dataset(dataset)
    stable = lambda value: [
        (
            case["case_id"],
            [
                (turn["actual"]["intent"], turn["actual"]["eligibility"], turn["actual"]["need_human"], turn["actual_tools"])
                for turn in case["turns"]
            ],
        )
        for case in value["cases"]
    ]
    report["summary"]["repeatable"] = stable(report) == stable(repeated)
    TICKET10_REPORT.parent.mkdir(parents=True, exist_ok=True)
    TICKET10_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "dataset_id": report.get("dataset_id"),
        "summary": report["summary"],
        "failures": report["failures"],
        "report": str(TICKET10_REPORT.relative_to(DEMO_HTML.parent)),
    }
