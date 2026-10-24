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

-- Добавляем сид для ЦОД в Хельсинки с координатами из тестового запроса
INSERT INTO datacenters (datacenter_id, name, bidding_zone, latitude, longitude, base_pue, max_power_kw)
VALUES ('FI-HELSINKI-01', 'Helsinki Nordic DC', 'FI', 60.1695, 24.9354, 1.150, 500.00)
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
