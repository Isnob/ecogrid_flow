# Source-to-Target Mapping (S2T): Open-Meteo Forecast $\to$ PostgreSQL

| Параметр документа | Значение |
| :--- | :--- |
| **Система-источник** | Open-Meteo Weather Forecast API |
| **Формат источника** | REST API (JSON, Columnar arrays) |
| **Эндпоинт** | `https://api.open-meteo.com/v1/forecast` |
| **Целевая система** | PostgreSQL 16 (On-Premise контур) |
| **Целевая таблица** | `open_meteo_forecast` |
| **Частота загрузки** | Каждые 3–6 часов (регулярный инкремент / upsert) |
| **Стратегия загрузки** | `UPSERT` (`INSERT ... ON CONFLICT (datacenter_id, forecast_time) DO UPDATE`) |

---

## 1. Параметры вызова API (Extraction Context)

Запрос формируется для каждого активного дата-центра из справочника `datacenters`:
```http
GET https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,shortwave_radiation&timezone=GMT&forecast_days=16
```

---

## 2. Матрица маппинга полей (Mapping Specification)

| № | Поле в JSON источника (Source Path) | Тип источника | Пример значения | Логика трансформации (Transformation Rule) | Колонка в БД (Target Column) | Тип данных PostgreSQL | Ограничения в БД | Уровень валидации (DQ) |
| :-: | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | *(Параметр запроса)* | `string` | `"FI-HELSINKI-01"` | ID площадки из справочника ЦОД при итерации ETL | `datacenter_id` | `VARCHAR(50)` | `NOT NULL`, FK $\to$ `datacenters` | База данных (FK) |
| **2** | `hourly.time[i]` | `string` (ISO 8601) | `"2026-10-24T00:00"` | Конвертация строки в дату UTC: `to_timestamp(...) AT TIME ZONE 'UTC'` | `forecast_time` | `TIMESTAMPTZ` | `NOT NULL`, PK | Python / База |
| **3** | `hourly.temperature_2m[i]` | `float / null` | `11.3` | Округление до 2 знаков | `temperature_2m` | `NUMERIC(5, 2)` | `NULLABLE` | Python (диапазон $[-50 \dots +50]^\circ\text{C}$) |
| **4** | `hourly.relative_humidity_2m[i]` | `int / null` | `94` | Относительная влажность (%) | `relative_humidity_2m` | `NUMERIC(5, 2)` | `NULLABLE` | Python (диапазон $[0 \dots 100]\%$) |
| **5** | `hourly.cloud_cover[i]` | `int / null` | `100` | Общая облачность (%) | `cloud_cover` | `NUMERIC(5, 2)` | `NULLABLE` | Python (диапазон $[0 \dots 100]\%$) |
| **6** | `hourly.wind_speed_10m[i]` | `float / null` | `20.9` | Скорость ветра (км/ч) | `wind_speed_10m` | `NUMERIC(5, 2)` | `NULLABLE` | Python ($\ge 0$) |
| **7** | `hourly.shortwave_radiation[i]` | `int / null` | `173` | Солнечная радиация GHI (Вт/м²) | `shortwave_radiation` | `NUMERIC(7, 2)` | `NULLABLE` | Python ($\ge 0$) |
| **8** | *(Системное время ETL)* | `datetime` | `2026-10-24 20:30:00+00` | Время фиксации пакета данных в БД: `NOW()` в UTC | `retrieved_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT NOW()` | База данных (DEFAULT) |

---

## 3. Архитектура обработки качества данных (Data Quality Gate)

* **Уровень базы данных:** База хранит чистые типы данных без жестких `CHECK`-ограничений, чтобы исключить падение транзакций при единичных сбойных значениях от сторонних API.
* **Уровень приложения (ETL):** Проверка диапазонов и аномалий возлагается на Python-слой перед загрузкой. Аномальные строки отсеиваются в журнал `dq_log`, а валидная часть партии беспрепятственно пишется в БД.
