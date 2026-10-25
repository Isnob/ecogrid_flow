# Source-to-Target Mapping (S2T): Open-Meteo Historical Weather $\to$ PostgreSQL

| Параметр документа | Значение |
| :--- | :--- |
| **Система-источник** | Open-Meteo Historical Weather API (Archive API) |
| **Формат источника** | REST API (JSON, Columnar arrays) |
| **Эндпоинт** | `https://archive-api.open-meteo.com/v1/archive` |
| **Целевая система** | PostgreSQL 16 (On-Premise контур) |
| **Целевая таблица** | `open_meteo_historical_weather` |
| **Частота загрузки** | Первичный ретроспективный Backfill за 3 года (`2023-10-01` – `now - 5 days`) + ежемесячный догруз |
| **Стратегия загрузки** | `UPSERT` (`INSERT ... ON CONFLICT (datacenter_id, observed_at) DO UPDATE`) |

---

## 1. Параметры вызова API (Extraction Context)

Запрос формируется для каждого активного дата-центра из справочника `datacenters`:
```http
GET https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={YYYY-MM-DD}&end_date={YYYY-MM-DD}&hourly=temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,shortwave_radiation&timezone=GMT
```

---

## 2. Матрица маппинга полей (Mapping Specification)

| № | Поле в JSON источника (Source Path) | Тип источника | Пример значения | Логика трансформации (Transformation Rule) | Колонка в БД (Target Column) | Тип данных PostgreSQL | Ограничения в БД | Уровень валидации (DQ) |
| :-: | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | *(Параметр запроса)* | `string` | `"FI-HELSINKI-01"` | ID площадки из справочника ЦОД при итерации ETL | `datacenter_id` | `VARCHAR(50)` | `NOT NULL`, FK $\to$ `datacenters` | База данных (FK) |
| **2** | `hourly.time[i]` | `string` (ISO 8601) | `"2023-10-01T00:00"` | Конвертация строки в дату UTC: `to_timestamp(...) AT TIME ZONE 'UTC'` | `observed_at` | `TIMESTAMPTZ` | `NOT NULL`, PK | Python / База |
| **3** | `hourly.temperature_2m[i]` | `float / null` | `10.8` | Фактическая температура воздуха (°C) | `temperature_2m` | `NUMERIC(5, 2)` | `NULLABLE` | Python (диапазон $[-50 \dots +50]^\circ\text{C}$) |
| **4** | `hourly.relative_humidity_2m[i]` | `int / null` | `92` | Относительная влажность (%) | `relative_humidity_2m` | `NUMERIC(5, 2)` | `NULLABLE` | Python (диапазон $[0 \dots 100]\%$) |
| **5** | `hourly.cloud_cover[i]` | `int / null` | `85` | Общая облачность (%) | `cloud_cover` | `NUMERIC(5, 2)` | `NULLABLE` | Python (диапазон $[0 \dots 100]\%$) |
| **6** | `hourly.wind_speed_10m[i]` | `float / null` | `15.4` | Скорость ветра (км/ч) | `wind_speed_10m` | `NUMERIC(5, 2)` | `NULLABLE` | Python ($\ge 0$) |
| **7** | `hourly.shortwave_radiation[i]` | `int / null` | `0` | Солнечная радиация GHI (Вт/м²) | `shortwave_radiation` | `NUMERIC(7, 2)` | `NULLABLE` | Python ($\ge 0$) |
| **8** | *(Системное время ETL)* | `datetime` | `2026-10-25 10:55:00+00` | Время фиксации пакета данных в БД: `NOW()` в UTC | `retrieved_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT NOW()` | База данных (DEFAULT) |

---

## 3. Архитектура обработки качества данных (Data Quality Gate)

* **Уровень базы данных:** База хранит валидные числовые типы без тяжелых `CHECK`-ограничений для отказоустойчивости пакетной вставки.
* **Идемпотентность:** Защита от дублей обеспечена составным первичным ключом `(datacenter_id, observed_at)` с механизмом `ON CONFLICT DO UPDATE`.
* **Уровень приложения (ETL):** Проверка физических границ параметров климата Европы перед записью в базу.
