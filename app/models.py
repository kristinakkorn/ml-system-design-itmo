from typing import Literal

from pydantic import BaseModel, Field


class TicketRequest(BaseModel):
    ticket_id: str | None = None
    channel: Literal["chat", "email", "web", "mobile"] = "web"
    subject: str = ""
    text: str = Field(min_length=3, max_length=10_000)
    locale: str = "ru-RU"


class Evidence(BaseModel):
    document_id: str
    source_type: Literal["knowledge_base", "historical_ticket"]
    title: str
    excerpt: str
    score: float


class DecisionResponse(BaseModel):
    ticket_id: str
    intent: str
    risk_level: Literal["low", "high"]
    risk_reasons: list[str]
    confidence: float
    route: str
    action: Literal["auto_reply", "agent_draft", "human_review"]
    draft: str | None
    evidence: list[Evidence]
    decision_reason: str
    latency_ms: int
    audit_id: str
    versions: dict[str, str]


class DemoScenario(BaseModel):
    name: str
    description: str
    request: TicketRequest
