from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.models import DecisionResponse, Evidence, TicketRequest


ROOT = Path(__file__).resolve().parents[1]

PIPELINE_VERSIONS = {
    "classifier": "rules-v1",
    "retriever": "tfidf-char-v1",
    "generator": "template-v1",
    "policy": "policy-v1",
}


@dataclass(frozen=True)
class Classification:
    intent: str
    confidence: float
    risk_level: str
    risk_reasons: list[str]


class RuleClassifier:
    """Transparent stand-in for the production fine-tuned encoder."""

    INTENT_PHRASES = {
        "password_reset": (
            "забыл пароль",
            "забыла пароль",
            "сбросить пароль",
            "не могу войти",
            "не получается войти",
        ),
        "payments": (
            "оплата",
            "платеж",
            "карта",
            "списали",
            "возврат",
            "деньги",
        ),
        "service_availability": (
            "не работает",
            "недоступен",
            "не открывается",
            "ошибка 503",
            "сервис лежит",
        ),
        "subscription": (
            "подписка",
            "отменить подписку",
            "отключить подписку",
        ),
    }

    RISK_PHRASES = {
        "charge_dispute": (
            "дважды списали",
            "не мой платеж",
            "не совершал платеж",
            "оспорить платеж",
            "верните деньги",
        ),
        "account_compromise": (
            "аккаунт взломали",
            "меня взломали",
            "украли аккаунт",
            "чужой вход",
        ),
        "privacy_request": (
            "удалите мои данные",
            "выгрузите мои данные",
            "персональные данные",
        ),
    }

    def classify(self, text: str) -> Classification:
        normalized = text.lower().replace("ё", "е")

        risk_reasons = [
            reason
            for reason, phrases in self.RISK_PHRASES.items()
            if any(phrase in normalized for phrase in phrases)
        ]

        scores = {
            intent: sum(phrase in normalized for phrase in phrases)
            for intent, phrases in self.INTENT_PHRASES.items()
        }
        intent, score = max(scores.items(), key=lambda item: item[1])
        if score == 0:
            intent, confidence = "unknown", 0.35
        elif score == 1:
            confidence = 0.84
        else:
            confidence = 0.96

        # Risk rules are deliberately independent from model confidence.
        return Classification(
            intent=intent,
            confidence=confidence,
            risk_level="high" if risk_reasons else "low",
            risk_reasons=risk_reasons,
        )


class LocalRetriever:
    """Small local vector search over KB articles and redacted history."""

    def __init__(self, kb_path: Path, history_path: Path) -> None:
        kb = json.loads(kb_path.read_text(encoding="utf-8"))
        history = json.loads(history_path.read_text(encoding="utf-8"))
        self.documents = kb + history
        corpus = [
            " ".join(
                [
                    item["title"],
                    item["content"],
                    " ".join(item.get("tags", [])),
                ]
            )
            for item in self.documents
        ]
        # A tiny dependency-free TF-IDF implementation is enough for seven docs.
        # Character n-grams handle Russian word forms and simple typos well.
        tokenized = [self._char_ngrams(text) for text in corpus]
        document_frequency = Counter(
            gram for grams in tokenized for gram in set(grams)
        )
        self.idf = {
            gram: math.log((1 + len(corpus)) / (1 + frequency)) + 1
            for gram, frequency in document_frequency.items()
        }
        self.document_vectors = [self._vectorize(grams) for grams in tokenized]

    def search(self, query: str, top_k: int = 3) -> list[Evidence]:
        query_vector = self._vectorize(self._char_ngrams(query))
        scores = [
            self._cosine(query_vector, document_vector)
            for document_vector in self.document_vectors
        ]
        ranked = sorted(
            range(len(scores)), key=lambda index: scores[index], reverse=True
        )[:top_k]
        return [
            Evidence(
                document_id=self.documents[index]["id"],
                source_type=self.documents[index]["source_type"],
                title=self.documents[index]["title"],
                excerpt=self.documents[index]["content"][:300],
                score=round(float(scores[index]), 4),
            )
            for index in ranked
            if scores[index] > 0
        ]

    @staticmethod
    def _char_ngrams(text: str) -> list[str]:
        normalized = text.lower().replace("ё", "е")
        grams: list[str] = []
        for word in normalized.split():
            clean_word = word.strip(".,!?;:«»\"")
            padded = f" {clean_word} "
            for size in range(3, 6):
                grams.extend(
                    padded[index : index + size]
                    for index in range(max(0, len(padded) - size + 1))
                )
        return grams

    def _vectorize(self, grams: list[str]) -> dict[str, float]:
        counts = Counter(grams)
        vector = {
            gram: (1 + math.log(count)) * self.idf[gram]
            for gram, count in counts.items()
            if gram in self.idf
        }
        norm = math.sqrt(sum(weight * weight for weight in vector.values()))
        if norm:
            return {gram: weight / norm for gram, weight in vector.items()}
        return {}

    @staticmethod
    def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
        if len(left) > len(right):
            left, right = right, left
        return sum(weight * right.get(gram, 0.0) for gram, weight in left.items())

    def get_document(self, document_id: str) -> dict | None:
        return next(
            (item for item in self.documents if item["id"] == document_id), None
        )


class AuditLogger:
    """Append-only JSONL audit. Raw ticket text is never written."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, record: dict) -> str:
        audit_id = str(uuid.uuid4())
        payload = {
            "audit_id": audit_id,
            "recorded_at": datetime.now(UTC).isoformat(),
            **record,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return audit_id


class TicketPipeline:
    AUTO_REPLY_ALLOWLIST = {"password_reset", "service_availability"}
    ROUTES = {
        "password_reset": "account_support_l1",
        "payments": "payments_l2",
        "service_availability": "technical_support_l1",
        "subscription": "subscription_support_l1",
        "unknown": "manual_triage",
    }
    RISK_ROUTES = {
        "charge_dispute": "payments_l2",
        "account_compromise": "security_l2",
        "privacy_request": "privacy_legal",
    }
    MIN_ROUTE_CONFIDENCE = 0.70
    MIN_RETRIEVAL_SCORE = 0.10

    def __init__(self, audit_path: Path) -> None:
        self.classifier = RuleClassifier()
        self.retriever = LocalRetriever(
            ROOT / "data" / "knowledge_base.json",
            ROOT / "data" / "historical_tickets.json",
        )
        self.audit = AuditLogger(audit_path)

    def process(self, ticket: TicketRequest) -> DecisionResponse:
        started = time.perf_counter()
        ticket_id = ticket.ticket_id or str(uuid.uuid4())
        query = f"{ticket.subject} {ticket.text}".strip()
        classification = self.classifier.classify(query)
        evidence = self.retriever.search(query)
        route = self._resolve_route(classification)

        action, reason = self._decide(classification, evidence)
        draft = self._make_draft(evidence, action)
        latency_ms = max(1, round((time.perf_counter() - started) * 1000))

        audit_id = self.audit.write(
            {
                "ticket_id": ticket_id,
                "channel": ticket.channel,
                "input_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                "intent": classification.intent,
                "confidence": classification.confidence,
                "risk_level": classification.risk_level,
                "risk_reasons": classification.risk_reasons,
                "route": route,
                "action": action,
                "decision_reason": reason,
                "evidence": [
                    {
                        "document_id": item.document_id,
                        "source_type": item.source_type,
                        "score": item.score,
                    }
                    for item in evidence
                ],
                "latency_ms": latency_ms,
                "versions": PIPELINE_VERSIONS,
            }
        )

        return DecisionResponse(
            ticket_id=ticket_id,
            intent=classification.intent,
            risk_level=classification.risk_level,
            risk_reasons=classification.risk_reasons,
            confidence=classification.confidence,
            route=route,
            action=action,
            draft=draft,
            evidence=evidence,
            decision_reason=reason,
            latency_ms=latency_ms,
            audit_id=audit_id,
            versions=PIPELINE_VERSIONS,
        )

    def _resolve_route(self, classification: Classification) -> str:
        if classification.risk_reasons:
            return self.RISK_ROUTES[classification.risk_reasons[0]]
        return self.ROUTES[classification.intent]

    def _decide(
        self, classification: Classification, evidence: list[Evidence]
    ) -> tuple[str, str]:
        if classification.risk_level == "high":
            return "human_review", "high_risk_policy"
        if classification.confidence < self.MIN_ROUTE_CONFIDENCE:
            return "human_review", "low_classifier_confidence"

        best_kb_score = max(
            (
                item.score
                for item in evidence
                if item.source_type == "knowledge_base"
            ),
            default=0.0,
        )
        if best_kb_score < self.MIN_RETRIEVAL_SCORE:
            return "human_review", "no_reliable_knowledge"
        if classification.intent in self.AUTO_REPLY_ALLOWLIST:
            return "auto_reply", "allowlisted_intent_and_checks_passed"
        return "agent_draft", "operator_approval_required"

    def _make_draft(
        self, evidence: list[Evidence], action: str
    ) -> str | None:
        if action == "human_review":
            return None

        kb_evidence = next(
            (item for item in evidence if item.source_type == "knowledge_base"),
            None,
        )
        if not kb_evidence:
            return None
        document = self.retriever.get_document(kb_evidence.document_id)
        if not document:
            return None
        # This deterministic template is the PoC replacement for local GLM + RAG.
        return document["response_template"]
