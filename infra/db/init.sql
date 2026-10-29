-- ============================================================
-- EcoGrid Flow: Инициализация схемы базы данных
-- ============================================================

-- 1. Справочник дата-центров (необходим для связи по внешнему ключу)
CREATE TABLE IF NOT EXISTS datacenters (
    datacenter_id   VARCHAR(50) PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    bidding_zone    VARCHAR(10) NOT NULL,
    latitude        NUMERIC(8, 5) NOT NULL,
    longitude       NUMERIC(8, 5) NOT NULL,
    base_pue        NUMERIC(4, 3) NOT NULL DEFAULT 1.200,
    max_power_kw    NUMERIC(10, 2) NOT NULL DEFAULT 1000.00,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Сид синтетических ЦОД по одному на энергозону MVP.
-- base_pue Хельсинки и Франкфурта взяты из BDD-сценария 1; base_pue Стокгольма предварительный,
-- значения уточняются по итогам ресерча PUE.
INSERT INTO datacenters (datacenter_id, name, bidding_zone, latitude, longitude, base_pue, max_power_kw)
VALUES
    ('FI-HELSINKI-01',  'Helsinki Nordic DC',   'FI',    60.1695, 24.9354, 1.150, 500.00),
    ('DE-FRANKFURT-01', 'Frankfurt Central DC', 'DE-LU', 50.1109,  8.6821, 1.250, 1000.00),
    ('SE-STOCKHOLM-01', 'Stockholm Nordic DC',  'SE3',   59.3293, 18.0686, 1.150, 500.00)
ON CONFLICT (datacenter_id) DO NOTHING;


-- 2. Таблица прогноза погоды (чистая, без CHECK-ограничений)
CREATE TABLE IF NOT EXISTS open_meteo_forecast (
    datacenter_id           VARCHAR(50) NOT NULL REFERENCES datacenters(datacenter_id) ON DELETE CASCADE,
    forecast_time           TIMESTAMPTZ NOT NULL,
    temperature_2m          NUMERIC(5, 2),
    relative_humidity_2m    NUMERIC(5, 2),
    cloud_cover             NUMERIC(5, 2),
    wind_speed_10m          NUMERIC(5, 2),
    shortwave_radiation     NUMERIC(7, 2),
    retrieved_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (datacenter_id, forecast_time)
);

-- Индекс по времени для быстрых выборок скользящего окна
CREATE INDEX IF NOT EXISTS idx_open_meteo_forecast_time 
    ON open_meteo_forecast (forecast_time);


-- 3. Таблица исторического архива погоды (для EDA и ML-моделей)
CREATE TABLE IF NOT EXISTS open_meteo_historical_weather (
    datacenter_id           VARCHAR(50) NOT NULL REFERENCES datacenters(datacenter_id) ON DELETE CASCADE,
    observed_at             TIMESTAMPTZ NOT NULL,
    temperature_2m          NUMERIC(5, 2),
    relative_humidity_2m    NUMERIC(5, 2),
    cloud_cover             NUMERIC(5, 2),
    wind_speed_10m          NUMERIC(5, 2),
    shortwave_radiation     NUMERIC(7, 2),
    retrieved_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (datacenter_id, observed_at)
);

-- Индекс по времени для аналитических выборок и бэктестов
CREATE INDEX IF NOT EXISTS idx_open_meteo_historical_time 
    ON open_meteo_historical_weather (observed_at);


-- 4. Реестр вычислительных задач клиентов
CREATE TABLE IF NOT EXISTS jobs (
    job_id                  VARCHAR(100) PRIMARY KEY,
    name                    VARCHAR(150),
    duration_minutes        INTEGER NOT NULL,
    required_power_kw       NUMERIC(10, 2) NOT NULL,
    earliest_start          TIMESTAMPTZ NOT NULL,
    deadline                TIMESTAMPTZ NOT NULL,
    preferred_datacenter_id VARCHAR(50) REFERENCES datacenters(datacenter_id) ON DELETE SET NULL,
    baseline_start          TIMESTAMPTZ,
    allow_geo_migration     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_created_at 
    ON jobs (created_at);


-- 5. Результаты расчёта и история рекомендаций оптимизатора
CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id       BIGSERIAL PRIMARY KEY,
    job_id                  VARCHAR(100) NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    datacenter_id           VARCHAR(50) NOT NULL REFERENCES datacenters(datacenter_id) ON DELETE CASCADE,
    recommended_start       TIMESTAMPTZ NOT NULL,
    recommended_end         TIMESTAMPTZ NOT NULL,
    estimated_energy_kwh    NUMERIC(12, 4) NOT NULL,
    estimated_cost          NUMERIC(12, 4) NOT NULL,
    baseline_cost           NUMERIC(12, 4) NOT NULL,
    estimated_savings       NUMERIC(12, 4) NOT NULL,
    currency                VARCHAR(3) NOT NULL DEFAULT 'EUR',
    is_fallback             BOOLEAN NOT NULL DEFAULT FALSE,
    calculated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recommendations_job_id 
    ON recommendations (job_id);

CREATE INDEX IF NOT EXISTS idx_recommendations_calculated_at
    ON recommendations (calculated_at);


-- 6. Цены Day-Ahead ENTSO-E (сырые интервалы в исходном шаге PT60M / PT15M, время в UTC)
CREATE TABLE IF NOT EXISTS entsoe_day_ahead_prices (
    bidding_zone            VARCHAR(10) NOT NULL,
    period_start            TIMESTAMPTZ NOT NULL,
    period_end              TIMESTAMPTZ NOT NULL,
    resolution              VARCHAR(10) NOT NULL,
    price                   NUMERIC(8, 2) NOT NULL,
    currency                VARCHAR(3) NOT NULL DEFAULT 'EUR',
    price_unit              VARCHAR(10) NOT NULL DEFAULT 'MWH',
    retrieved_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (bidding_zone, period_start, resolution)
);

-- Индекс по времени для выборок окна расчёта по всем зонам
CREATE INDEX IF NOT EXISTS idx_entsoe_prices_period_start
    ON entsoe_day_ahead_prices (period_start);


-- DQ Gate: идемпотентное обновление существующей БД. DDL на ревью Богдану.
ALTER TABLE entsoe_day_ahead_prices ADD COLUMN IF NOT EXISTS imputation_method TEXT;
ALTER TABLE open_meteo_forecast ADD COLUMN IF NOT EXISTS imputation_method TEXT;

CREATE TABLE IF NOT EXISTS etl_dq_log (
    event_id BIGSERIAL PRIMARY KEY,
    batch_id UUID NOT NULL,
    source TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_etl_dq_log_batch ON etl_dq_log (batch_id);
CREATE INDEX IF NOT EXISTS idx_etl_dq_log_recorded ON etl_dq_log (recorded_at);

-- 7. Только полные часы. Реальный ряд предпочтительнее восстановленного;
-- при одинаковом качестве PT60M предпочтительнее PT15M.
-- Новый столбец добавлен в конец, чтобы CREATE OR REPLACE работал на прежней БД.
CREATE OR REPLACE VIEW v_entsoe_prices_hourly AS
SELECT bidding_zone, hour_start, price, currency, price_unit,
       source_resolution, points_count, is_estimated
FROM (
    SELECT bidding_zone,
           date_trunc('hour', period_start, 'UTC') AS hour_start,
           ROUND(AVG(price), 2) AS price,
           MIN(currency) AS currency,
           MIN(price_unit) AS price_unit,
           resolution AS source_resolution,
           COUNT(*) AS points_count,
           BOOL_OR(imputation_method IS NOT NULL) AS is_estimated,
           ROW_NUMBER() OVER (
               PARTITION BY bidding_zone, date_trunc('hour', period_start, 'UTC')
               ORDER BY BOOL_OR(imputation_method IS NOT NULL),
                        CASE resolution WHEN 'PT60M' THEN 1 ELSE 2 END
           ) AS resolution_rank
    FROM entsoe_day_ahead_prices
    WHERE currency = 'EUR' AND price_unit = 'MWH' AND price BETWEEN -500 AND 4000
      AND period_start = date_trunc('minute', period_start)
      AND ((resolution = 'PT60M' AND period_end - period_start = INTERVAL '1 hour'
            AND EXTRACT(MINUTE FROM period_start AT TIME ZONE 'UTC') = 0)
        OR (resolution = 'PT15M' AND period_end - period_start = INTERVAL '15 minutes'
            AND EXTRACT(MINUTE FROM period_start AT TIME ZONE 'UTC')::int % 15 = 0))
    GROUP BY bidding_zone, date_trunc('hour', period_start, 'UTC'), resolution
    HAVING COUNT(*) = CASE resolution WHEN 'PT60M' THEN 1 WHEN 'PT15M' THEN 4 END
) ranked
WHERE resolution_rank = 1;
