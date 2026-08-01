# Support Ticket Automation PoC

Демо решения:
![demo](demo/demo-ml-itmo.mp4)


Минимальный работающий прототип к архитектуре из
[architecture.md](architecture.md). Он демонстрирует полный путь:

```text
mock-ticket → classification/risk → local retrieval → policy → draft/route → audit
```

## Что можно показать на защите

1. **Happy path:** «Я забыла пароль и не могу войти». Система определяет
   `password_reset`, находит статью KB, формирует grounded draft и разрешает
   `auto_reply`.
2. **Risky path:** «С карты дважды списали деньги». Система определяет
   `charge_dispute`, запрещает автозакрытие и направляет тикет в `payments_l2` с
   действием `human_review`.
3. Дополнительно: неизвестный запрос получает низкий confidence и уходит в
   `manual_triage`.

Каждое решение записывается в `runtime/audit.jsonl`. Исходный текст туда не
попадает: сохраняются SHA-256, labels, scores, источники и версии компонентов.

## Быстрый запуск через Docker Compose

```bash
docker compose up --build
```

- UI: <http://localhost:8501>
- Swagger API: <http://localhost:8000/docs>
- healthcheck: <http://localhost:8000/health>

### Ошибка `CERTIFICATE_VERIFY_FAILED` при Docker build

В Dockerfile PyPI-хосты уже переданы в `PIP_TRUSTED_HOST`, поэтому повторите
сборку без старого неуспешного слоя:

```bash
docker compose build --no-cache
docker compose up
```

Сообщение `No matching distribution found` в этом случае вторично: `pip` не
увидел список версий из-за TLS-ошибки, а не потому, что FastAPI отсутствует.

`trusted-host` отключает проверку сертификата только для `pypi.org` и
`files.pythonhosted.org`; это практичный fallback для локального PoC за
корпоративным proxy. Для production правильнее добавить корневой сертификат
компании в trust store образа и собрать с пустым параметром:

```bash
PIP_TRUSTED_HOST= docker compose build --no-cache
```

## Локальный запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

В другом терминале:

```bash
source .venv/bin/activate
streamlit run ui.py
```

## Запуск тестов

```bash
pytest -q
```

Тесты фиксируют главную safety-гарантию: risky и low-confidence тикеты никогда
не получают `auto_reply`.

## Пример API

```bash
curl -s http://localhost:8000/api/v1/tickets/process \
  -H 'Content-Type: application/json' \
  -d '{
    "channel": "chat",
    "subject": "Двойное списание",
    "text": "С карты дважды списали деньги. Верните деньги за платеж."
  }'
```

## Что здесь упрощено

| В PoC | В целевой архитектуре |
|---|---|
| ключевые слова и правила | fine-tuned encoder + calibrated confidence + hard-risk rules |
| TF-IDF char vectors в памяти | BM25 + dense embeddings + vector DB + reranker |
| 7 локальных JSON-документов | версионируемая KB и обезличенная история с ACL/freshness |
| готовый шаблон ответа | RAG → локальная GLM → разрешённый внешний LLM fallback |
| один FastAPI-процесс | stateless replicas, event bus и отдельные async workers |
| JSONL audit | append-only/WORM storage с RBAC и retention policy |
| синхронный вызов всего pipeline | routing синхронный, retrieval/generation асинхронные |

Упрощение намеренное: PoC доказывает связность компонентов и правильное решение
policy, но не производительность, качество на реальном распределении или
production-безопасность.

## Структура

```text
app/main.py        API и demo-сценарии
app/pipeline.py    classifier, retrieval, policy, draft, audit
app/models.py      API-контракты
data/              мини-KB и обезличенная история
ui.py              Streamlit UI
tests/             happy, risky и low-confidence paths
```
