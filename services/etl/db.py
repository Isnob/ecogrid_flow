"""
Модуль для работы с PostgreSQL: управление подключениями и сохранение данных ETL-пайплайнов.
"""

import os
from typing import List, Set, Tuple
import psycopg


def get_connection():
    """
    Создаёт соединение с PostgreSQL.
    Берёт параметры из переменных окружения.
    Дефолты — 5432, localhost, ecogrid.
    """
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "ecogrid"),
        user=os.getenv("POSTGRES_USER", "ecogrid"),
        password=os.getenv("POSTGRES_PASSWORD", "ecogrid_dev_password"),
    )


def get_active_datacenters(conn) -> List[Tuple[str, float, float]]:
    """
    Возвращает список активных площадок: [(datacenter_id, latitude, longitude), ...]
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT datacenter_id, latitude, longitude FROM datacenters WHERE is_active = TRUE;"
        )
        return cur.fetchall()


def save_weather_forecast(conn, datacenter_id: str, records: List[Tuple]) -> int:
    """
    Пакетная вставка нормализованного прогноза погоды с обновлением при совпадении ключа (UPSERT).
    Формат каждого кортежа в records:
    (forecast_time, temperature_2m, relative_humidity_2m, cloud_cover, wind_speed_10m, shortwave_radiation)
    """
    if not records:
        return 0

    # Формируем строки для вставки, добавляя datacenter_id
    rows = [
        (datacenter_id, rec[0], rec[1], rec[2], rec[3], rec[4], rec[5])
        for rec in records
    ]

    query = """
    INSERT INTO open_meteo_forecast (
        datacenter_id,
        forecast_time,
        temperature_2m,
        relative_humidity_2m,
        cloud_cover,
        wind_speed_10m,
        shortwave_radiation,
        retrieved_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
    ON CONFLICT (datacenter_id, forecast_time)
    DO UPDATE SET
        temperature_2m       = EXCLUDED.temperature_2m,
        relative_humidity_2m = EXCLUDED.relative_humidity_2m,
        cloud_cover          = EXCLUDED.cloud_cover,
        wind_speed_10m       = EXCLUDED.wind_speed_10m,
        shortwave_radiation  = EXCLUDED.shortwave_radiation,
        retrieved_at         = NOW();
    """

    with conn.cursor() as cur:
        cur.executemany(query, rows)
    conn.commit()

    return len(rows)


def save_day_ahead_prices(conn, records: List[Tuple]) -> int:
    """
    Пакетная вставка цен Day-Ahead с обновлением при совпадении ключа (UPSERT).
    Формат каждого кортежа в records:
    (bidding_zone, period_start, period_end, resolution, price, currency, price_unit)
    """
    if not records:
        return 0

    query = """
    INSERT INTO entsoe_day_ahead_prices (
        bidding_zone,
        period_start,
        period_end,
        resolution,
        price,
        currency,
        price_unit,
        retrieved_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
    ON CONFLICT (bidding_zone, period_start, resolution)
    DO UPDATE SET
        period_end   = EXCLUDED.period_end,
        price        = EXCLUDED.price,
        currency     = EXCLUDED.currency,
        price_unit   = EXCLUDED.price_unit,
        retrieved_at = NOW();
    """

    with conn.cursor() as cur:
        cur.executemany(query, records)
    conn.commit()

    return len(records)


def get_zones_with_prices(conn, period_start, period_end) -> Set[str]:
    """
    Возвращает энергозоны, по которым в БД есть цены в интервале [period_start; period_end).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT bidding_zone FROM entsoe_day_ahead_prices
            WHERE period_start >= %s AND period_start < %s;
            """,
            (period_start, period_end),
        )
        return {row[0] for row in cur.fetchall()}


def save_historical_weather(conn, datacenter_id: str, records: List[Tuple]) -> int:
    """
    Пакетная вставка исторического архива погоды с обновлением при совпадении ключа (UPSERT).
    Формат каждого кортежа в records:
    (observed_at, temperature_2m, relative_humidity_2m, cloud_cover, wind_speed_10m, shortwave_radiation)
    """
    if not records:
        return 0

    rows = [
        (datacenter_id, rec[0], rec[1], rec[2], rec[3], rec[4], rec[5])
        for rec in records
    ]

    query = """
    INSERT INTO open_meteo_historical_weather (
        datacenter_id,
        observed_at,
        temperature_2m,
        relative_humidity_2m,
        cloud_cover,
        wind_speed_10m,
        shortwave_radiation,
        retrieved_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
    ON CONFLICT (datacenter_id, observed_at)
    DO UPDATE SET
        temperature_2m       = EXCLUDED.temperature_2m,
        relative_humidity_2m = EXCLUDED.relative_humidity_2m,
        cloud_cover          = EXCLUDED.cloud_cover,
        wind_speed_10m       = EXCLUDED.wind_speed_10m,
        shortwave_radiation  = EXCLUDED.shortwave_radiation,
        retrieved_at         = NOW();
    """

    with conn.cursor() as cur:
        cur.executemany(query, rows)
    conn.commit()

    return len(rows)

