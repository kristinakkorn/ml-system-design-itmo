import os
from pathlib import Path

from fastapi import FastAPI

from app.models import DecisionResponse, DemoScenario, TicketRequest
from app.pipeline import ROOT, TicketPipeline


def create_app(audit_path: Path | None = None) -> FastAPI:
    application = FastAPI(
        title="Support Ticket Automation PoC",
        version="0.1.0",
        description="Rules + local retrieval + policy gate + audit log",
    )
    resolved_audit_path = audit_path or Path(
        os.getenv("AUDIT_LOG_PATH", ROOT / "runtime" / "audit.jsonl")
    )
    pipeline = TicketPipeline(resolved_audit_path)
    application.state.pipeline = pipeline

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/v1/demo/scenarios", response_model=list[DemoScenario])
    def demo_scenarios() -> list[DemoScenario]:
        return [
            DemoScenario(
                name="Happy path",
                description="Безопасный сброс пароля: найден KB и разрешён автоответ.",
                request=TicketRequest(
                    channel="web",
                    subject="Не могу войти",
                    text="Я забыла пароль и не могу войти. Как сбросить пароль?",
                ),
            ),
            DemoScenario(
                name="Risky path",
                description="Спорное списание: обязательная эскалация оператору.",
                request=TicketRequest(
                    channel="chat",
                    subject="Двойное списание",
                    text="С карты дважды списали деньги. Верните деньги за платеж.",
                ),
            ),
            DemoScenario(
                name="Low-confidence path",
                description="Неизвестная тема: безопасная triage-очередь.",
                request=TicketRequest(
                    channel="mobile",
                    subject="Нужна помощь",
                    text="У меня странная ситуация, помогите разобраться.",
                ),
            ),
        ]

    @application.post(
        "/api/v1/tickets/process", response_model=DecisionResponse
    )
    def process_ticket(ticket: TicketRequest) -> DecisionResponse:
        return pipeline.process(ticket)

    return application


app = create_app()
