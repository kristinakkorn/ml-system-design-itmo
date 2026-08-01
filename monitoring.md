# Мониторинг

## 1. Что должно быть на главном dashboard

| Уровень | Метрики |
|---|---|
| Технический | входящий RPS, ошибки, p50/p95/p99, event-bus lag, размер очередей, saturation CPU/GPU, доступность БД/search/LLM |
| ML routing | распределение классов/confidence, abstain/OOD rate, ошибки маршрута и число переводов между очередями |
| RAG/LLM | retrieval no-result, citation/groundedness failures, local/external fallback rate, cache hit, tokens и latency |
| Safety | заблокированные auto-send, PII detections, prompt-injection flags, high-risk false negatives по проверенной выборке |
| Продукт | SLA первого ответа, resolution time, auto-resolution, AHT, CSAT, reopen 24ч/7д, backlog |

Метрики режутся по каналу, языку, категории, model/prompt/policy version и
auto/manual cohort. Иначе общая средняя скрывает проблему редкой категории.

## 2. Стартовые алерты

| Условие | Реакция |
|---|---|
| p95 hot path > 500 мс 5 минут или error rate > 1% | on-call; проверить router/DB, перейти на rules/default queue |
| event-bus oldest message > 2 минуты | масштабировать workers; отключить дорогую генерацию low priority |
| прогноз нарушения 15-минутного SLA или backlog > 2× нормы | incident alert поддержке и платформе |
| external LLM error > 10% или p95 > 10 с | открыть circuit breaker, оставить local GLM/manual |
| PII обнаружены в отправляемом prompt/output | немедленно отключить внешний LLM и auto-send, security incident |
| risk recall на размеченной delayed-выборке ниже 98% | выключить auto-actions затронутого класса |
| class/OOD/fallback rate изменился > 30% к сезонному baseline | data/ML investigation |
| дневной LLM budget использован на 80% раньше 18:00 | ограничить внешний fallback, проверить всплеск/цикл retry |

Точные пороги уточняются после 2–4 недель baseline-наблюдения. Алерт должен иметь
runbook и владельца; всё остальное остаётся dashboard-метрикой.

## 3. Как отличить поломку модели от изменения потока

| Наблюдение | Вероятная причина | Проверка |
|---|---|---|
| Ошибки выросли, входные распределения прежние | деградация модели/релиза | сравнить с предыдущей моделью в shadow и откатить canary |
| Резко изменились темы, слова, embeddings и OOD | новый продукт или инцидент | посмотреть error codes, канал, кластеры и события сервиса |
| Confidence прежний, но delayed labels хуже | concept drift / устарела taxonomy | ручная выборка, confusion matrix, финальные очереди |
| Offline replay хороший, online latency/ошибки плохие | serving/infrastructure | ресурсы, timeouts, версии tokenizer/features |
| Только один канал ухудшился | сломался adapter/формат | schema, encoding, очистка email/app payload |

Нужны три независимых сигнала: **input drift**, **качество на свежих labels** и
**сравнение с контрольной моделью**. Один drift score не доказывает деградацию.

## 4. Мониторинг стоимости LLM

Для каждого вызова сохраняются provider/model, local/external, input/output
tokens, cache hit, latency, retry, категория, стоимость и результат
`auto-sent / accepted / edited / rejected` — без исходного PII-текста.

Главные показатели:

- `₽ / входящий тикет`, `₽ / draft`, `₽ / успешно решённый тикет`;
- доля запросов template → local GLM → external LLM;
- токены и стоимость по категории/часу/model version;
- стоимость бесполезных вызовов: timeout, reject, duplicate, reopen;
- budget burn rate и прогноз до конца дня.

Ограничители: per-request token cap, часовой/дневной бюджет, semantic cache,
внешний fallback только по allowlist и circuit breaker от повторных retry.

## 5. Решается ли бизнес-задача

Baseline ручной обработки: `200 000 × 150 ₽ = 30 млн ₽/день`. Типовой поток —
80 000 тикетов/день. Осторожная целевая гипотеза — безопасно автоматически
решать **20% общего потока** (половину типового):

```text
40 000 авто-решённых тикетов × 150 ₽ = 6 млн ₽/день валовой мощности
net effect = валовая мощность − LLM/infra cost − стоимость повторной обработки
```

Эта оценка не означает немедленного сокращения затрат на персонал: эффект может
проявиться в меньшем backlog, overtime и времени ответа. Успех фиксируется, если
одновременно:

- ≥ 90% тикетов получают первый ответ за 15 минут;
- CSAT не ниже 4,2 на pilot и затем растёт к 4,3;
- reopen снижается с 9% к 7,5%, а не растёт из-за автоответов;
- auto-resolution достигает 20% без роста safety-инцидентов;
- AHT снижается у agent-assist cohort;
- положителен `net effect`, рассчитанный по фактической стоимости.

Поэтому A/B-тест сравнивает не «ответила ли модель», а корректное решение без
повторного обращения за 7 дней, CSAT, SLA и стоимость на такое решение.
