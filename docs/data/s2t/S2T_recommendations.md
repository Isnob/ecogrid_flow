# Source-to-Target Mapping (S2T): Optimization Core Result $\to$ PostgreSQL `recommendations`

| Параметр документа | Значение |
| :--- | :--- |
| **Система-источник** | Расчётное ядро оптимизатора EcoGrid Flow (Optimization Core / Memory Object) |
| **Формат источника** | Pydantic-результат ядра без ID; API сохраняет результат и добавляет ID из БД в HTTP-ответ |
| **Целевая система** | PostgreSQL 16 (On-Premise) & Ответ API клиенту (`JSON 200 OK`) |
| **Целевая таблица** | `recommendations` |
| **Частота загрузки** | По факту генерации рекомендации движком скользящего окна |
| **Стратегия загрузки** | `INSERT` (`BIGSERIAL` PK) |

---

## 1. Контекст источника (Optimization Core Engine Output)

Результат расчёта скользящего окна формируется после перебора доступных площадок и временных слотов с учётом почасового PUE от температуры:
```
cost(t)  = power_kw × PUE(T_t) / 1000 × price_eur_per_mwh(t) × (занятые минуты / 60)
savings  = baseline_cost − estimated_cost
```

---

## 2. Матрица маппинга полей (Mapping Specification)

| № | Поле в объекте ядра (Source Attribute) | Тип источника | Пример значения | Логика трансформации (Calculation & Transformation Rule) | Колонка в БД (Target Column) | Тип данных PostgreSQL | Ограничения в БД | Наличие в ответе API |
| :-: | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| **1** | *(Автоинкремент БД)* | `integer` | `1042` | Первичный ключ генерируется последовательностью PostgreSQL | `recommendation_id` | `BIGSERIAL` | `NOT NULL`, PK | `recommendation_id` |
| **2** | `job.job_id` | `string` | `"airflow_dag_train_model_20261025"` | Внешний ключ задачи, для которой производился расчёт | `job_id` | `VARCHAR(100)` | `NOT NULL`, FK $\to$ `jobs` | `job_id` |
| **3** | `target_datacenter` | `string` | `"FI-HELSINKI-01"` | Площадка выбранного окна | `datacenter_id` | `VARCHAR(50)` | `NOT NULL`, FK $\to$ `datacenters` | `target_datacenter` |
| **4** | `recommended_start` | `datetime (UTC)`| `"2026-10-25T23:00:00Z"` | Начало выбранного окна на границе часа | `recommended_start` | `TIMESTAMPTZ` | `NOT NULL` | `recommended_start` |
| **5** | `recommended_end` | `datetime (UTC)`| `"2026-10-26T03:00:00Z"` | `recommended_start + duration_minutes` без округления | `recommended_end` | `TIMESTAMPTZ` | `NOT NULL` | `recommended_end` |
| **6** | `hourly_costs[].pue` + `job.required_power_kw` | `float` | `2300.00` | API суммирует `power_kw × PUE × (занятые минуты / 60)` по часам окна | `estimated_energy_kwh` | `NUMERIC(12, 4)` | `NOT NULL` | *(Аналитика)* |
| **7** | `estimated_cost_eur` | `float` | `112.50` | Сумма `hourly_costs[].cost_eur` (€) | `estimated_cost` | `NUMERIC(12, 4)` | `NOT NULL` | `estimated_cost_eur` |
| **8** | `baseline_cost_eur` | `float` | `145.00` | Базовая стоимость в preferred ЦОД (€) | `baseline_cost` | `NUMERIC(12, 4)` | `NOT NULL` | `baseline_cost_eur` |
| **9** | `estimated_savings_eur` | `float` | `32.50` | `baseline_cost − estimated_cost` | `estimated_savings` | `NUMERIC(12, 4)` | `NOT NULL` | `estimated_savings_eur` |
| **10** | *(Фиксированная валюта)* | `string` | `"EUR"` | Валюта расчёта биржевых цен (ISO 4217) | `currency` | `VARCHAR(3)` | `NOT NULL DEFAULT 'EUR'` | *(контекст)* |
| **11** | `is_fallback` | `boolean` | `false` | `false` — выбранное и базовое окна только с реальными ценами; `true` — оценочная цена хотя бы в одном из них (ADR-001) | `is_fallback` | `BOOLEAN` | `NOT NULL DEFAULT FALSE` | `is_fallback` |
| **12** | *(Системное время)* | `datetime` | `2026-10-25 14:00:02+00` | Время генерации рекомендации: `NOW()` в UTC | `calculated_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT NOW()` | *(timestamp)* |

---

## 3. Бизнес-ограничения и целостность (Integrity Gate)

* **Дедлайн (`FR-ENG-03`):** `recommended_end <= job.deadline`. Ядру запрещено рекомендовать более дешёвое окно, если оно нарушает дедлайн клиента.
* **Непрерывность (`FR-ENG-02`):** Дробление задачи запрещено, окно непрерывно (`recommended_end - recommended_start = duration_minutes`).
* **Экономия:** В ответе API клиенту дополнительно возвращается процент экономии:
  `estimated_savings_percent = estimated_savings_eur / baseline_cost_eur × 100`; при `baseline_cost_eur = 0` — JSON `null`. Отрицательные стоимости и экономия допустимы.
* **Транзакционность:** Запись рекомендации в БД и формирование ответа клиенту выполняются в единой атомарной транзакции. При ошибке БД транзакция откатывается.
