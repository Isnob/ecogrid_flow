# Контракт расчетного ядра

Контракт K3 отделяет расчетное ядро от БД и REST API. API Саня собирает
почасовые данные из БД, превращает их в `EngineRequest` и передает в
`recommend(...)`. Ядро возвращает `EngineResponse`; API может отдать его
почти без преобразований.

## Что принимает ядро

`EngineRequest` содержит параметры задачи, ограничения по зонам и список
дата-центров. Для каждого ЦОД API передает почасовые строки:

- `price_eur_per_mwh` — цена электричества, включая отрицательные спотовые цены;
- `temperature_c` — температура для расчета PUE;
- `price_is_estimated` — признак, что цена получена fallback-оценкой.

Все даты и время должны быть в UTC и передаваться как ISO 8601 с суффиксом
`Z`. Почасовые строки должны начинаться ровно с начала часа, идти в
хронологическом порядке и не содержать дубликатов. Сетка ядра — один час.
`duration_minutes` может быть не кратен 60: последний час тарифицируется
пропорционально, а его фактическое количество минут передается в
`HourCost.minutes`. Ядро не читает БД и не вызывает внешние API.

## Что возвращает ядро

`EngineResponse` содержит `job_id` и не больше двух рекомендаций. Каждая
рекомендация покрывает поля FR-API-03:

- `target_datacenter`, `recommended_start`, `recommended_end`;
- `estimated_cost_eur`, `baseline_cost_eur`;
- `estimated_savings_eur`, `estimated_savings_percent`;
- `is_fallback`.

Дополнительно `hourly_costs` содержит стоимость каждого часа выбранного окна
для графика Максима: цену, температуру, PUE, стоимость часа и признак
оценочной цены.

`is_fallback=false` означает подтвержденную рекомендацию: в расчете окна и
базовой стоимости использованы только реальные цены. Она исполняется
клиентом по умолчанию. Поле `baseline_has_estimated_price` явно сообщает,
использовалась ли оценочная цена в baseline; ядро проверяет, что это согласуется
с `is_fallback`.

`is_fallback=true` означает оценочный вариант. Он не запускается автоматически.
Если подтвержденного окна нет, в ответе остается только fallback, а `reason`
имеет значение `no_confirmed_window`. Если базовое окно само задевает часы
без реальной цены, используется причина `baseline_estimated`.

`recommendation_id` на стороне ядра может быть `null`: числовой идентификатор
назначает API при сохранении рекомендации в БД. В HTTP-ответе API должен вернуть
уже назначенный идентификатор.

`estimated_savings_percent` может быть `null`, если `baseline_cost_eur == 0`,
потому что процент экономии в этом случае не определен. Стоимости и экономия
могут быть отрицательными при отрицательных спотовых ценах.

Успешный ответ содержит хотя бы одну рекомендацию. Если нет даже оценочных
цен и рассчитать вариант невозможно, ядро возвращает пустой список и
`reason="data_unavailable"`; API преобразует эту ситуацию в HTTP 503.

## Пример

```python
from datetime import datetime, timezone

from services.engine.contracts import EngineRequest, recommend

request = EngineRequest(
    job_id="job-123",
    duration_minutes=120,
    required_power_kw=100.0,
    earliest_start=datetime(2026, 11, 3, 10, tzinfo=timezone.utc),
    deadline=datetime(2026, 11, 4, 10, tzinfo=timezone.utc),
    allowed_zones=["FI"],
    preferred_datacenter_id="dc-fi-1",
    baseline_start=datetime(2026, 11, 3, 10, tzinfo=timezone.utc),
    datacenters=[
        {
            "datacenter_id": "dc-fi-1",
            "zone": "FI",
            "base_pue": 1.10,
            "max_power_kw": 500.0,
            "hours": [
                {
                    "timestamp": "2026-11-03T10:00:00Z",
                    "minutes": 60,
                    "price_eur_per_mwh": 42.5,
                    "temperature_c": 4.0,
                    "price_is_estimated": False,
                },
                {
                    "timestamp": "2026-11-03T11:00:00Z",
                    "minutes": 60,
                    "price_eur_per_mwh": 39.0,
                    "temperature_c": 4.5,
                    "price_is_estimated": False,
                },
            ],
        }
    ],
)

response = recommend(request)  # реализация появится в следующей задаче
```

Для отсутствия подтвержденного окна API проверяет
`response.reason == "no_confirmed_window"` и не пытается исполнить
рекомендацию с `is_fallback=true`.
