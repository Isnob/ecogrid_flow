# Source-to-Target Mapping (S2T): API Request Payload $\to$ PostgreSQL `jobs`

| Параметр документа | Значение |
| :--- | :--- |
| **Система-источник** | API Gateway / Клиентский оркестратор (Apache Airflow, Kubeflow, Web UI) |
| **Формат источника** | HTTP POST Request Body (JSON) |
| **Эндпоинт** | `POST /api/v1/recommendations` |
| **Целевая система** | PostgreSQL 16 (On-Premise контур) |
| **Целевая таблица** | `jobs` |
| **Частота загрузки** | По событию (Event-driven, при каждом обращении клиента) |
| **Стратегия загрузки** | `INSERT` с валидацией или `UPSERT` (`ON CONFLICT (job_id) DO UPDATE`) |

---

## 1. Пример входящего запроса (Source Context)

```json
{
  "job_id": "airflow_dag_train_model_20261025",
  "name": "LLM Fine-Tuning 7B",
  "duration_minutes": 240,
  "required_power_kw": 500.0,
  "earliest_start": "2026-10-25T14:00:00Z",
  "deadline": "2026-10-26T14:00:00Z",
  "preferred_datacenter_id": "FI-HELSINKI-01",
  "baseline_start": "2026-10-25T14:00:00Z",
  "allow_geo_migration": true
}
```

---

## 2. Матрица маппинга полей (Mapping Specification)

| № | Поле в JSON запроса (Source Path) | Тип источника | Пример значения | Логика трансформации / Значение по умолчанию | Колонка в БД (Target Column) | Тип данных PostgreSQL | Ограничения в БД | Уровень валидации (DQ / API) |
| :-: | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `$.job_id` | `string` | `"airflow_dag_train_model_20261025"` | Если отсутствует — генерируется UUID: `job_{uuid.uuid4().hex[:12]}` | `job_id` | `VARCHAR(100)` | `NOT NULL`, PK | API Gateway (валидация строки) |
| **2** | `$.name` | `string / null` | `"LLM Fine-Tuning 7B"` | Передаётся как есть (человекочитаемое имя для UI) | `name` | `VARCHAR(150)` | `NULLABLE` | API Gateway (max len 150) |
| **3** | `$.duration_minutes` | `integer` | `240` | Длительность выполнения в минутах | `duration_minutes` | `INTEGER` | `NOT NULL` | API Gateway (`> 0`) |
| **4** | `$.required_power_kw` | `float` | `500.00` | Оценочная электрическая мощность вычислений | `required_power_kw` | `NUMERIC(10, 2)` | `NOT NULL` | API Gateway (`> 0.0`) |
| **5** | `$.earliest_start` | `string (ISO 8601)` | `"2026-10-25T14:00:00Z"` | Если не передано — default `NOW()` в UTC | `earliest_start` | `TIMESTAMPTZ` | `NOT NULL` | API Gateway (валидность таймстемпа) |
| **6** | `$.deadline` | `string (ISO 8601)` | `"2026-10-26T14:00:00Z"` | Преобразуется в UTC | `deadline` | `TIMESTAMPTZ` | `NOT NULL` | API (`deadline >= earliest_start + duration`) |
| **7** | `$.preferred_datacenter_id`| `string / null` | `"FI-HELSINKI-01"` | Если не указан — default первая площадка | `preferred_datacenter_id` | `VARCHAR(50)` | `NULLABLE`, FK $\to$ `datacenters` | API / База (FK) |
| **8** | `$.baseline_start` | `string (ISO 8601) / null`| `"2026-10-25T14:00:00Z"` | Если не указан — default `earliest_start` | `baseline_start` | `TIMESTAMPTZ` | `NULLABLE` | API (интервал `[earliest_start; deadline - duration]`) |
| **9** | `$.allow_geo_migration` | `boolean` | `true` | Если не указан — default `true` | `allow_geo_migration` | `BOOLEAN` | `NOT NULL DEFAULT TRUE` | API Gateway |
| **10** | *(Системное время)* | `datetime` | `2026-10-25 14:00:00+00` | Время поступления запроса: `NOW()` в UTC | `created_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT NOW()` | База данных (DEFAULT) |

---

## 3. Бизнес-валидация и отказоустойчивость (Validation Gate)

* **HTTP 422 Unprocessable Entity:** Запрос отклоняется без сохранения в базу, если:
  1. `duration_minutes <= 0` или `required_power_kw <= 0`.
  2. `deadline < earliest_start + duration_minutes` (невозможно выполнить задачу до дедлайна, требование `FR-API-02`).
  3. `preferred_datacenter_id` не существует в реестре активных дата-центров.
  4. `baseline_start` выходит за границы интервала допустимого планирования.
* **Идемпотентность:** Повторный запрос с идентичным `job_id` обновляет параметры задачи без создания дубликатов строк в таблице.
