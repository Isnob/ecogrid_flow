# K4. POST /api/v1/recommendations

Контракт HTTP для формы веб-портала и оркестратора. Основание: [FR-API-01…03](../REQUIREMENTS.md#fr-api-01), [ADR-001](../adr/ADR-001-engine-input-data.md) и [ADR-002](../adr/ADR-002-db-api-contract.md). Исполняемые модели находятся в [`services/api/schemas.py`](../../services/api/schemas.py). Эндпоинт пока не реализован.

## Запрос

`POST /api/v1/recommendations` с `Content-Type: application/json` и `Authorization: Bearer <API_TOKEN>`.

| Поле | Тип | Правило |
| :--- | :--- | :--- |
| `job_id` | строка, 1–100 символов | Идентификатор задачи; повторный запрос с тем же ID пересчитывает рекомендацию |
| `duration_minutes` | целое > 0 | Непрерывная длительность задачи в минутах |
| `required_power_kw` | число > 0 | IT-мощность в кВт |
| `deadline` | дата/время UTC | Завершение задачи должно быть не позже этого момента |
| `earliest_start` | дата/время UTC, необязательно | По умолчанию момент приёма запроса (`now`) |
| `allowed_zones` | непустой список уникальных строк | Допустимые энергозоны; в MVP: `DE-LU`, `FI`, `SE3` |
| `preferred_datacenter_id` | строка, необязательно | ЦОД базового сценария; по умолчанию первый активный ЦОД первой зоны из `allowed_zones` |
| `baseline_start` | дата/время UTC, необязательно | По умолчанию `earliest_start`; начало базового сценария |

Все времена в JSON передаются в ISO 8601 с `Z` или `+00:00`; API возвращает `Z`. Другая зона и время без зоны отклоняются. `deadline` должен быть не раньше `earliest_start + duration_minutes`. `baseline_start` должен лежать в закрытом интервале от `earliest_start` до `deadline − duration_minutes`.

Поиск рекомендованного окна идёт по началам часов UTC. Если `earliest_start` приходится на середину часа, первый кандидат начинается в следующий полный час; конец окна равен началу плюс **точно** `duration_minutes` и не округляется. Цена и PUE берутся из почасовой строки. Стоимость каждого затронутого часа равна `required_power_kw × PUE × price_eur_per_mwh / 1000 × (занятые минуты / 60)`. Например, для задачи на 90 минут со стартом в 10:00 час 10:00–11:00 оплачивается целиком, час 11:00–12:00 — наполовину, а `recommended_end` равен 11:30. Базовый сценарий начинается ровно в `baseline_start`, даже если это не граница часа; его первый и последний часы также оплачиваются пропорционально пересечению с интервалом задачи. Часовой ряд должен содержать все затронутые часы без пропусков и дублей, с метками начала часа UTC.

Pydantic проверяет структуру, числа и интервалы. API при обращении к БД проверяет существование зон и ЦОД, активность ЦОД, принадлежность `preferred_datacenter_id` к `allowed_zones` и доступную мощность. Если ЦОД первой зоны несколько, API выбирает первый по `datacenter_id` в лексикографическом порядке; если ни одного нет, возвращает `422`.

```http
POST /api/v1/recommendations HTTP/1.1
Authorization: Bearer <API_TOKEN>
Content-Type: application/json

{
  "job_id": "job-123",
  "duration_minutes": 120,
  "required_power_kw": 100,
  "earliest_start": "2026-11-03T10:00:00Z",
  "deadline": "2026-11-04T10:00:00Z",
  "allowed_zones": ["FI"],
  "preferred_datacenter_id": "FI-HELSINKI-01",
  "baseline_start": "2026-11-03T10:00:00Z"
}
```

## Успешный ответ: `200 OK`

`recommendations` содержит один или два элемента, не больше одного для каждого значения `is_fallback`. `false` означает подтверждённый вариант: цены окна **и базового сценария** реальны. Airflow исполняет только этот элемент. `true` означает оценочный вариант: хотя бы одна цена в окне либо базовом сценарии оценочная. Он предназначен для показа человеку и не запускается автоматически.

| Поле | Тип | Смысл |
| :--- | :--- | :--- |
| `job_id` | строка | ID из запроса |
| `recommendations[].recommendation_id` | целое > 0 | ID сохранённой строки `recommendations`, назначает БД после расчёта |
| `target_datacenter` | строка | ID выбранного ЦОД |
| `recommended_start`, `recommended_end` | дата/время UTC | Выбранное непрерывное окно; конец не позже дедлайна |
| `estimated_cost_eur`, `baseline_cost_eur` | числа | Стоимость окна и базового сценария, EUR |
| `estimated_savings_eur` | число | `baseline_cost_eur − estimated_cost_eur` |
| `estimated_savings_percent` | число или `null` | `estimated_savings_eur / baseline_cost_eur × 100`; `null`, если базовая стоимость равна нулю |
| `is_fallback` | boolean | Признак использования оценочной цены |
| `hourly_costs` | непустой список | Почасовая детализация выбранного окна для графика |
| `hourly_costs[].timestamp` | дата/время UTC | Начало часа |
| `hourly_costs[].minutes` | целое от 1 до 60 | Сколько минут выбранного окна приходится на этот час |
| `hourly_costs[].price_eur_per_mwh` | число | Цена, EUR/МВт⋅ч; может быть отрицательной |
| `hourly_costs[].temperature_c` | число или `null` | Наружная температура; `null` означает расчёт с `base_pue` |
| `hourly_costs[].pue` | число ≥ 1 | PUE этого часа |
| `hourly_costs[].cost_eur` | число | Стоимость этого часа; может быть отрицательной |
| `hourly_costs[].price_is_estimated` | boolean | Использована ли оценочная цена этого часа |
| `reason` | `null`, `no_confirmed_window` или `baseline_estimated` | Причина отсутствия основной рекомендации; при наличии основной всегда `null` |

Если основной рекомендации нет, список содержит только оценочный вариант. `no_confirmed_window` означает, что ни одно окно не покрыто реальными ценами целиком. `baseline_estimated` означает, что подтверждённое окно найти можно, но базовый сценарий использует оценочную цену; она влияет на показатель экономии. Если выполняются обе причины, используется `no_confirmed_window`. Airflow в обоих случаях запускает задачу по своему обычному расписанию (`baseline_start`) и может повторить запрос после публикации цен. Для графика фронт использует `hourly_costs` каждой рекомендации; это точки выбранных окон, а не все варианты поиска.

`hourly_costs[].timestamp` — начало затронутого часа. Записи идут подряд без пропусков от `recommended_start` до последнего часа с непустым пересечением с интервалом `[recommended_start, recommended_end)`; `minutes` равно длине этого пересечения, а стоимость часа уже пропорциональна занятым минутам. Отрицательные цены могут дать отрицательные `cost_eur`, `estimated_cost_eur`, `baseline_cost_eur` и `estimated_savings_eur`. Процент вычисляется по формуле выше и при отрицательном знаменателе может выглядеть непривычно; фронт не должен считать его неотрицательным. При нулевом `baseline_cost_eur` процент равен JSON `null`, а сумма экономии сохраняет числовое значение.

Пример с подтверждённым и оценочным вариантами (стоимости приведены для демонстрации формата):

```json
{
  "job_id": "job-123",
  "recommendations": [
    {
      "recommendation_id": 101,
      "target_datacenter": "FI-HELSINKI-01",
      "recommended_start": "2026-11-03T11:00:00Z",
      "recommended_end": "2026-11-03T13:00:00Z",
      "estimated_cost_eur": 8.51,
      "baseline_cost_eur": 9.3725,
      "estimated_savings_eur": 0.8625,
      "estimated_savings_percent": 9.20245,
      "is_fallback": false,
      "hourly_costs": [
        {"timestamp": "2026-11-03T11:00:00Z", "minutes": 60, "price_eur_per_mwh": 39, "temperature_c": 4.5, "pue": 1.15, "cost_eur": 4.485, "price_is_estimated": false},
        {"timestamp": "2026-11-03T12:00:00Z", "minutes": 60, "price_eur_per_mwh": 35, "temperature_c": 5, "pue": 1.15, "cost_eur": 4.025, "price_is_estimated": false}
      ]
    },
    {
      "recommendation_id": 102,
      "target_datacenter": "FI-HELSINKI-01",
      "recommended_start": "2026-11-04T07:00:00Z",
      "recommended_end": "2026-11-04T09:00:00Z",
      "estimated_cost_eur": 6.9,
      "baseline_cost_eur": 9.3725,
      "estimated_savings_eur": 2.4725,
      "estimated_savings_percent": 26.38037,
      "is_fallback": true,
      "hourly_costs": [
        {"timestamp": "2026-11-04T07:00:00Z", "minutes": 60, "price_eur_per_mwh": 30, "temperature_c": 3, "pue": 1.15, "cost_eur": 3.45, "price_is_estimated": true},
        {"timestamp": "2026-11-04T08:00:00Z", "minutes": 60, "price_eur_per_mwh": 30, "temperature_c": 3.5, "pue": 1.15, "cost_eur": 3.45, "price_is_estimated": true}
      ]
    }
  ],
  "reason": null
}
```

При отсутствии подтверждённой рекомендации ответ по-прежнему `200 OK`:

```json
{
  "job_id": "job-456",
  "recommendations": [{
    "recommendation_id": 103,
    "target_datacenter": "FI-HELSINKI-01",
    "recommended_start": "2026-11-04T07:00:00Z",
    "recommended_end": "2026-11-04T09:00:00Z",
    "estimated_cost_eur": 6.9,
    "baseline_cost_eur": 9.3725,
    "estimated_savings_eur": 2.4725,
    "estimated_savings_percent": 26.38037,
    "is_fallback": true,
    "hourly_costs": [
      {"timestamp": "2026-11-04T07:00:00Z", "minutes": 60, "price_eur_per_mwh": 30, "temperature_c": 3, "pue": 1.15, "cost_eur": 3.45, "price_is_estimated": true},
      {"timestamp": "2026-11-04T08:00:00Z", "minutes": 60, "price_eur_per_mwh": 30, "temperature_c": 3.5, "pue": 1.15, "cost_eur": 3.45, "price_is_estimated": true}
    ]
  }],
  "reason": "no_confirmed_window"
}
```

Если подтверждённое окно существует, но базовый сценарий использует оценочную цену, ответ имеет один элемент с `is_fallback: true` и `reason: "baseline_estimated"`. Если оценочных данных недостаточно даже для одного варианта, успешного ответа нет: API возвращает `503 data_unavailable`.

## Ошибки

Во всех ошибках один JSON-формат. `details` — список указаний на поля; для ошибок без привязки к полю он пуст. API преобразует стандартные ошибки валидации FastAPI/Pydantic в этот формат. Ошибка `422` не создаёт запись в `jobs`.

| HTTP | `error.code` | Когда |
| :--- | :--- | :--- |
| `401` | `unauthorized` | Нет Bearer-токена или он неверный |
| `422` | `invalid_request` | Неверный тип/значение поля, недопустимый интервал, неизвестная зона или неподходящий ЦОД |
| `503` | `data_unavailable` | Нет данных для расчёта даже оценочного варианта (например, нет архива для медианы) |
| `500` | `internal_error` | Сбой расчёта или записи результата; транзакция откатывается |

```json
{
  "error": {
    "code": "invalid_request",
    "message": "Invalid recommendation request",
    "details": [
      {"field": "baseline_start", "message": "Must be within the allowed execution window"}
    ]
  }
}
```

Ошибки `401`, `503` и `500` используют ту же оболочку с соответствующим `code` и пустым `details`. Поле `reason` относится только к успешному ответу и не является HTTP-ошибкой.

Пример отсутствия данных даже для оценки:

```json
{"error": {"code": "data_unavailable", "message": "Not enough price data to calculate a recommendation", "details": []}}
```

## Стык с расчётным ядром

API собирает `EngineRequest`, вызывает `recommend(...)`, сохраняет `jobs` и каждый элемент результата одной транзакцией, затем присваивает внешние `recommendation_id` из `BIGSERIAL`. Поле `recommendation_id` в результате ядра может быть `null` и не используется для HTTP-ответа; внутреннее `baseline_has_estimated_price` также не выводится наружу. При пустом `EngineResponse` с `reason=data_unavailable` API возвращает `503 data_unavailable`. На один запрос API возвращает не больше одной основной и одной оценочной рекомендации.
