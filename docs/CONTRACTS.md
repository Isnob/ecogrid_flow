# 📜 Спецификация контрактов данных и API (Contract-First Specification)

**Проект:** EcoGrid Flow (On-Premise B2B-сервис оптимизации ресурсоемких вычислений)  
**Команда:** «Шпингалеты» (*Shpingalets*)  
**Версия спецификации:** 1.0.0  
**Статус:** Согласовано (Baseline для параллельной разработки)  

---

## 1. Зачем нужен этот документ?

Разработка системы ведётся по принципу **Contract-First**:
* **Богдан (ETL / Ingestion):** пишет парсеры, которые гарантированно приводят данные к контрактам `MarketDataRecord` и `WeatherDataRecord`.
* **Саня (Backend / DevOps):** создаёт таблицы PostgreSQL и Pydantic-схемы FastAPI строго по этим структурам.
* **Максим (Frontend):** берёт TypeScript-интерфейсы из этого документа и сразу верстает интерфейс на моковых данных, не дожидаясь готовности бэкенда.
* **Гриша (QA):** пишет тесты валидации граничных значений и генераторы синтетических аномалий по правилам валидации из этих схем.
* **Арина (Data / ML):** использует эти поля как целевые признаки при обучении моделей и расчете формулы PUE.

---

## 2. Контракты сбора данных (Ingestion Data Contracts)

### 2.1. Контракт рыночных данных: `MarketDataRecord`
*Источник:* ENTSO-E Transparency Platform (Day-Ahead Prices & Generation).  
*Периодичность:* раз в сутки (с 13:00 CET) с дискретностью 1 час (или 15 минут).

| Поле | Тип | Обязательное | Ограничения / Формат | Описание |
| :--- | :--- | :---: | :--- | :--- |
| `timestamp_utc` | `datetime (ISO 8601)` | Да | `YYYY-MM-DDTHH:mm:ssZ` | Время начала интервала в UTC |
| `energy_zone` | `string` | Да | `DE`, `FI`, `SE`, `UK`, `FR` | Код европейской ценовой зоны |
| `price_eur_mwh` | `float` | Да | `-500.0` ... `+4000.0` | Спотовая цена за 1 МВт⋅ч в евро (может быть отрицательной) |
| `price_eur_kwh` | `float` | Да | `price_eur_mwh / 1000.0` | Рассчитанная цена за 1 кВт⋅ч |
| `carbon_intensity_g_kwh` | `float` | Нет | `0.0` ... `1200.0` | Углеродоемкость сети (г CO₂ на кВт⋅ч) |
| `is_forecast` | `boolean` | Да | `true` для Day-Ahead | Флаг прогнозных биржевых цен |

```json
{
  "timestamp_utc": "2026-11-09T23:00:00Z",
  "energy_zone": "FI",
  "price_eur_mwh": 38.45,
  "price_eur_kwh": 0.03845,
  "carbon_intensity_g_kwh": 65.2,
  "is_forecast": true
}
```

---

### 2.2. Контракт метеорологических данных: `WeatherDataRecord`
*Источник:* Open-Meteo Forecast & Historical Weather API.  
*Периодичность:* каждые 3–6 часов с шагом 1 час.

| Поле | Тип | Обязательное | Ограничения / Формат | Описание |
| :--- | :--- | :---: | :--- | :--- |
| `timestamp_utc` | `datetime (ISO 8601)` | Да | `YYYY-MM-DDTHH:mm:ssZ` | Время прогноза в UTC |
| `datacenter_id` | `string` | Да | Идентификатор ЦОД (FK) | Например: `FI-HELSINKI-01` |
| `temperature_celsius` | `float` | Да | `-50.0` ... `+60.0` | Температура уличного воздуха (критична для PUE) |
| `wind_speed_ms` | `float` | Нет | `0.0` ... `100.0` | Скорость ветра на высоте 10 м (м/с) |
| `relative_humidity_pct` | `float` | Нет | `0.0` ... `100.0` | Относительная влажность воздуха (%) |

```json
{
  "timestamp_utc": "2026-11-09T23:00:00Z",
  "datacenter_id": "FI-HELSINKI-01",
  "temperature_celsius": -2.4,
  "wind_speed_ms": 5.1,
  "relative_humidity_pct": 82.0
}
```

---

### 2.3. Справочник инфраструктуры клиента: `DatacenterProfile`
*Хранение:* PostgreSQL таблица `client_infrastructure`. Не покидает контур On-Premise.

```json
{
  "datacenter_id": "FI-HELSINKI-01",
  "name": "Helsinki Nordic Hub",
  "country": "FI",
  "energy_zone": "FI",
  "latitude": 60.1699,
  "longitude": 24.9384,
  "base_pue": 1.15,
  "free_cooling_max_temp": 16.0,
  "chiller_cop": 3.5,
  "total_capacity_kw": 1500.0
}
```

---

## 3. Контракты REST API (FastAPI Backend ↔ React Frontend & Airflow)

Базовый URL: `/api/v1`

---

### 3.1. Эндпоинт: `POST /api/v1/recommendations`
**Назначение:** Основной метод аналитического ядра. Принимает параметры вычислительной задачи клиента и возвращает глобально оптимальный временной слот и локацию с гарантией дедлайна.

#### Входной контракт (Request Payload: `OptimizationRequest`):

| Поле | Тип | Обязательное | Валидация / Ограничения | Описание |
| :--- | :--- | :---: | :--- | :--- |
| `task_id` | `string` | Да | `UUID` или строка | Уникальный ID задачи во внешней системе |
| `task_name` | `string` | Да | `1..100` символов | Название (например, `LLM-Fine-Tuning`) |
| `task_duration_hours` | `integer` | Да | `1 <= duration <= 48` | Длительность непрерывных вычислений (в часах) |
| `deadline_utc` | `datetime` | Да | `deadline > now + duration` | Крайний срок сдачи результатов по SLA (UTC) |
| `power_consumption_kw` | `float` | Да | `> 0.0` | Средняя мощность потребления серверов задачи |
| `allowed_regions` | `list[string]` | Нет | Список кодов зон (`DE`, `FI`, `SE`) | Ограничения по суверенитету данных. Если пуст — доступны все ЦОД клиента |

```json
{
  "task_id": "d8e3b4a2-8f12-4c56-9a1b-9e2c4d6f8a01",
  "task_name": "LLM-Fine-Tuning",
  "task_duration_hours": 5,
  "deadline_utc": "2026-11-10T09:00:00Z",
  "power_consumption_kw": 120.0,
  "allowed_regions": ["DE", "FI", "SE"]
}
```

---

#### Выходной контракт (Response Payload: `OptimizationResponse`):

| Поле | Тип | Описание |
| :--- | :--- | :--- |
| `task_id` | `string` | Эхо переданного ID задачи |
| `status` | `string` | `SUCCESS` или `FALLBACK_BASELINE` |
| `recommended_start_time_utc` | `datetime` | Оптимальный час запуска вычислений |
| `recommended_end_time_utc` | `datetime` | Время завершения задачи (`start_time + duration`) |
| `target_datacenter` | `string` | Идентификатор выбранного ЦОД |
| `target_region` | `string` | Выбранная энергозона |
| `expected_cost_eur` | `float` | Расчетная стоимость электроэнергии с учетом PUE |
| `baseline_cost_eur` | `float` | Стоимость при обычном «слепом» немедленном старте по cron |
| `savings_eur` | `float` | Абсолютная экономия в евро (`baseline - expected`) |
| `savings_percent` | `float` | Относительная экономия бюджета (%) |
| `expected_co2_kg` | `float` | Расчетные выбросы CO₂ (кг) |
| `pue_applied` | `float` | Средний динамический PUE за интервал задачи |
| `explanation` | `string` | Человекочитаемое инженерное обоснование выбора |

```json
{
  "task_id": "d8e3b4a2-8f12-4c56-9a1b-9e2c4d6f8a01",
  "status": "SUCCESS",
  "recommended_start_time_utc": "2026-11-09T23:00:00Z",
  "recommended_end_time_utc": "2026-11-10T04:00:00Z",
  "target_datacenter": "FI-HELSINKI-01",
  "target_region": "FI",
  "expected_cost_eur": 42.50,
  "baseline_cost_eur": 89.20,
  "savings_eur": 46.70,
  "savings_percent": 52.35,
  "expected_co2_kg": 39.12,
  "pue_applied": 1.16,
  "explanation": "Выбран дата-центр FI-HELSINKI-01: сочетание ночного провала тарифов в Финляндии (38.4 €/МВт⋅ч) и температуры -2.4°C позволило задействовать 100% Free Cooling без включения чиллеров."
}
```

---

### 3.2. Обработка ошибок (Error Responses)

* **HTTP 422 Unprocessable Entity (`DeadlineUnreachable`):**  
  Если `deadline_utc` наступает раньше, чем `текущее_время + task_duration_hours`:
  ```json
  {
    "error_code": "DEADLINE_UNREACHABLE",
    "message": "Дедлайн 2026-11-09T14:00:00Z наступает раньше минимального времени выполнения (требуется 5ч)."
  }
  ```
* **HTTP 503 Service Unavailable (`MarketDataMissing`):**  
  Если внешняя биржа еще не опубликовала данные Day-Ahead на запрашиваемую дату:
  ```json
  {
    "error_code": "MARKET_DATA_MISSING",
    "message": "Котировки Day-Ahead для региона FI на указанный интервал еще не опубликованы (публикация после 13:00 CET)."
  }
  ```

---

## 4. Готовые структуры для разработчиков

### 4.1. TypeScript интерфейсы (для Максима в React / Frontend)

```typescript
// types/api.ts

export interface OptimizationRequest {
  taskId: string;
  taskName: string;
  taskDurationHours: number;
  deadlineUtc: string; // ISO 8601
  powerConsumptionKw: number;
  allowedRegions?: string[];
}

export interface OptimizationResponse {
  taskId: string;
  status: 'SUCCESS' | 'FALLBACK_BASELINE';
  recommendedStartTimeUtc: string;
  recommendedEndTimeUtc: string;
  targetDatacenter: string;
  targetRegion: string;
  expectedCostEur: number;
  baselineCostEur: number;
  savingsEur: number;
  savingsPercent: number;
  expectedCo2Kg: number;
  pueApplied: number;
  explanation: string;
}

export interface MarketPricePoint {
  timestampUtc: string;
  energyZone: string;
  priceEurMwh: number;
}
```

---

### 4.2. Pydantic V2 схемы на Python (для Сани в FastAPI, Богдана в ETL и Гриши в QA)

```python
# schemas/contracts.py
from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional

class MarketDataRecord(BaseModel):
    timestamp_utc: datetime
    energy_zone: str = Field(..., min_length=2, max_length=5)
    price_eur_mwh: float = Field(..., ge=-500.0, le=4000.0)
    price_eur_kwh: float
    carbon_intensity_g_kwh: Optional[float] = Field(None, ge=0.0)
    is_forecast: bool = True

class WeatherDataRecord(BaseModel):
    timestamp_utc: datetime
    datacenter_id: str
    temperature_celsius: float = Field(..., ge=-50.0, le=60.0)
    wind_speed_ms: Optional[float] = Field(None, ge=0.0)
    relative_humidity_pct: Optional[float] = Field(None, ge=0.0, le=100.0)

class OptimizationRequest(BaseModel):
    task_id: str
    task_name: str = Field(..., min_length=1, max_length=100)
    task_duration_hours: int = Field(..., ge=1, le=48)
    deadline_utc: datetime
    power_consumption_kw: float = Field(..., gt=0.0)
    allowed_regions: Optional[List[str]] = Field(default_factory=list)

class OptimizationResponse(BaseModel):
    task_id: str
    status: str
    recommended_start_time_utc: datetime
    recommended_end_time_utc: datetime
    target_datacenter: str
    target_region: str
    expected_cost_eur: float
    baseline_cost_eur: float
    savings_eur: float
    savings_percent: float
    expected_co2_kg: float
    pue_applied: float
    explanation: str
```
