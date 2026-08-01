import json

from fastapi.testclient import TestClient

from app.main import create_app


def make_client(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    return TestClient(create_app(audit_path)), audit_path


def test_happy_path_returns_grounded_auto_reply_and_audit(tmp_path):
    client, audit_path = make_client(tmp_path)
    raw_text = "Я забыла пароль и не могу войти. Как сбросить пароль?"

    response = client.post(
        "/api/v1/tickets/process",
        json={
            "channel": "web",
            "subject": "Не могу войти",
            "text": raw_text,
        },
    )

    assert response.status_code == 200
    decision = response.json()
    assert decision["intent"] == "password_reset"
    assert decision["risk_level"] == "low"
    assert decision["action"] == "auto_reply"
    assert decision["route"] == "account_support_l1"
    assert "Забыли пароль?" in decision["draft"]
    assert any(
        item["document_id"] == "kb-password-reset"
        for item in decision["evidence"]
    )

    audit = json.loads(audit_path.read_text(encoding="utf-8").strip())
    assert audit["action"] == "auto_reply"
    assert audit["audit_id"] == decision["audit_id"]
    assert raw_text not in audit_path.read_text(encoding="utf-8")
    assert len(audit["input_sha256"]) == 64


def test_risky_payment_is_always_escalated_without_draft(tmp_path):
    client, audit_path = make_client(tmp_path)

    response = client.post(
        "/api/v1/tickets/process",
        json={
            "channel": "chat",
            "subject": "Двойное списание",
            "text": "С карты дважды списали деньги. Верните деньги за платеж.",
        },
    )

    assert response.status_code == 200
    decision = response.json()
    assert decision["intent"] == "payments"
    assert decision["risk_level"] == "high"
    assert "charge_dispute" in decision["risk_reasons"]
    assert decision["action"] == "human_review"
    assert decision["route"] == "payments_l2"
    assert decision["decision_reason"] == "high_risk_policy"
    assert decision["draft"] is None

    audit = json.loads(audit_path.read_text(encoding="utf-8").strip())
    assert audit["risk_level"] == "high"
    assert audit["action"] == "human_review"


def test_unknown_intent_falls_back_to_manual_triage(tmp_path):
    client, _ = make_client(tmp_path)

    response = client.post(
        "/api/v1/tickets/process",
        json={
            "channel": "mobile",
            "subject": "Нужна помощь",
            "text": "У меня странная ситуация, помогите разобраться.",
        },
    )

    decision = response.json()
    assert decision["intent"] == "unknown"
    assert decision["confidence"] < 0.70
    assert decision["action"] == "human_review"
    assert decision["route"] == "manual_triage"
    assert decision["decision_reason"] == "low_classifier_confidence"
