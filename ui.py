import os

import requests
import streamlit as st


BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

FALLBACK_SCENARIOS = {
    "Happy path — сброс пароля": {
        "channel": "web",
        "subject": "Не могу войти",
        "text": "Я забыла пароль и не могу войти. Как сбросить пароль?",
    },
    "Risky path — двойное списание": {
        "channel": "chat",
        "subject": "Двойное списание",
        "text": "С карты дважды списали деньги. Верните деньги за платеж.",
    },
    "Low confidence — неизвестная тема": {
        "channel": "mobile",
        "subject": "Нужна помощь",
        "text": "У меня странная ситуация, помогите разобраться.",
    },
}


st.set_page_config(page_title="Support AI PoC", page_icon="🎫", layout="wide")
st.title("🎫 Support Ticket Automation PoC")
st.caption(
    "Rule classifier → local retrieval → policy gate → draft/route → audit"
)

scenario_name = st.selectbox("Демо-сценарий", list(FALLBACK_SCENARIOS))
scenario = FALLBACK_SCENARIOS[scenario_name]

with st.form("ticket_form"):
    channel = st.selectbox(
        "Канал", ["chat", "email", "web", "mobile"],
        index=["chat", "email", "web", "mobile"].index(scenario["channel"]),
    )
    subject = st.text_input("Тема", value=scenario["subject"])
    text = st.text_area("Текст тикета", value=scenario["text"], height=130)
    submitted = st.form_submit_button("Обработать тикет", type="primary")

if submitted:
    try:
        response = requests.post(
            f"{BACKEND_URL}/api/v1/tickets/process",
            json={"channel": channel, "subject": subject, "text": text},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as error:
        st.error(f"Backend недоступен: {error}")
        st.stop()

    if result["action"] == "auto_reply":
        st.success("Проверки пройдены: разрешён автоматический ответ")
    elif result["action"] == "agent_draft":
        st.warning("Ответ требует подтверждения оператора")
    else:
        st.error("Автозакрытие запрещено: тикет эскалирован оператору")

    left, right = st.columns(2)
    with left:
        st.subheader("1. Классификация и policy")
        st.metric("Intent", result["intent"])
        st.metric("Confidence", f'{result["confidence"]:.0%}')
        st.write("**Risk:**", result["risk_level"])
        if result["risk_reasons"]:
            st.write("**Причины риска:**", ", ".join(result["risk_reasons"]))
        st.write("**Маршрут:**", result["route"])
        st.write("**Действие:**", result["action"])
        st.write("**Policy reason:**", result["decision_reason"])

    with right:
        st.subheader("2. Найденные источники")
        for item in result["evidence"]:
            with st.expander(
                f'{item["source_type"]}: {item["title"]} ({item["score"]:.3f})'
            ):
                st.write(item["excerpt"])

    st.subheader("3. Результат")
    if result["draft"]:
        st.info(result["draft"])
    else:
        st.write("Черновик намеренно не создан — решение должен принять оператор.")

    st.subheader("4. Аудит")
    st.code(
        f'audit_id={result["audit_id"]}\n'
        f'ticket_id={result["ticket_id"]}\n'
        f'latency_ms={result["latency_ms"]}\n'
        f'versions={result["versions"]}'
    )

with st.sidebar:
    st.header("Что демонстрируется")
    st.markdown(
        """
        - быстрый локальный routing;
        - retrieval по маленькой KB и истории;
        - запрет risky/low-confidence auto-close;
        - понятная причина решения;
        - воспроизводимый audit log.
        """
    )
    st.caption(f"Backend: {BACKEND_URL}")
