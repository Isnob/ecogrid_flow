"""
Оркестратор ETL-пайплайна сбора метеопрогнозов для активных дата-центров.
"""

from collectors.open_meteo import fetch_weather_forecast
from db import get_connection, get_active_datacenters
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from psycopg.types.json import Jsonb


def number(value, low, high):
    if value is None or isinstance(value, bool):
        return False
    try:
        value = Decimal(str(value))
        return value.is_finite() and low <= value <= high
    except (InvalidOperation, ValueError, TypeError):
        return False


def aware(value):
    return isinstance(value, datetime) and value.utcoffset() is not None


def weather_errors(row):
    if not isinstance(row, (tuple, list)) or len(row) != 6:
        return ["invalid_row_shape"]
    errors = []
    if not aware(row[0]) or row[0].minute or row[0].second or row[0].microsecond:
        errors.append("invalid_timestamp")
    if not number(row[1], -50, 50):
        errors.append("temperature_out_of_range")
    if not number(row[2], 0, 100):
        errors.append("humidity_out_of_range")
    # Optional columns must also fit PostgreSQL NUMERIC; null is allowed.
    for value, bound in zip(row[3:], (999.99, 999.99, 99999.99)):
        if value is not None and not number(value, -bound, bound):
            errors.append("invalid_optional_numeric")
    return errors


def event(reason, payload):
    return {"reason": reason, "payload": payload}


def validate(records, validator, key):
    good, events = {}, []
    for row in records:
        errors = validator(row)
        if errors:
            events.append(event(",".join(errors), row))
        elif key(row) in good:
            events.append(event("duplicate_interval", row))
        else:
            good[key(row)] = tuple(row)
    return list(good.values()), events


def grid(start, end, step):
    while start < end:
        yield start
        start += step


def prepare_weather(records):
    """Fill internal hourly gaps from a genuine neighbour at most one hour away.

    Never extend the forecast horizon or recursively use restored observations.
    """
    valid, events = validate(records, weather_errors, lambda r: r[0])
    stamps = [r[0] for r in records if isinstance(r, (tuple, list)) and r and aware(r[0])
              and not (r[0].minute or r[0].second or r[0].microsecond)]
    if not stamps:
        return [], events
    genuine = {r[0]: r for r in valid}
    result = [r + (None,) for r in valid]
    for stamp in grid(min(stamps), max(stamps) + timedelta(hours=1), timedelta(hours=1)):
        if stamp in genuine:
            continue
        neighbours = [r for r in valid if abs(r[0] - stamp) <= timedelta(hours=1)]
        if neighbours:
            neighbour = min(neighbours, key=lambda r: (abs(r[0] - stamp), r[0]))
            result.append((stamp,) + neighbour[1:] + ("nearest_hour",))
            events.append(event("gap_filled_nearest_hour", {"time": stamp, "source_time": neighbour[0]}))
        else:
            events.append(event("gap_unfilled_no_neighbour", {"time": stamp}))
    return result, events


def json_safe(value):
    # JSONB rejects NaN/Infinity: retain these original values as strings.
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (datetime, Decimal)):
        return str(value)
    if isinstance(value, float) and (value != value or abs(value) == float("inf")):
        return str(value)
    return value


def write_events(cur, source, entity, events):
    batch_id = uuid4()
    cur.executemany(
        """INSERT INTO etl_dq_log (batch_id, source, entity_id, reason, payload)
           VALUES (%s, %s, %s, %s, %s)""",
        [(batch_id, source, entity, e["reason"], Jsonb(json_safe(e["payload"]))) for e in events],
    )


def save_checked_weather(conn, dc_id, records):
    rows, events = prepare_weather(records)
    if not records:
        events.append({"reason": "empty_forecast", "payload": []})
    with conn.transaction(), conn.cursor() as cur:
        write_events(cur, "weather", dc_id, events)
        cur.executemany(
            """INSERT INTO open_meteo_forecast
               (datacenter_id, forecast_time, temperature_2m, relative_humidity_2m,
                cloud_cover, wind_speed_10m, shortwave_radiation, imputation_method)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (datacenter_id, forecast_time) DO UPDATE SET
                 temperature_2m = EXCLUDED.temperature_2m,
                 relative_humidity_2m = EXCLUDED.relative_humidity_2m,
                 cloud_cover = EXCLUDED.cloud_cover, wind_speed_10m = EXCLUDED.wind_speed_10m,
                 shortwave_radiation = EXCLUDED.shortwave_radiation,
                 imputation_method = EXCLUDED.imputation_method, retrieved_at = NOW()
               WHERE EXCLUDED.imputation_method IS NULL
                  OR open_meteo_forecast.imputation_method IS NOT NULL""",
            [(dc_id,) + r for r in rows],
        )
    return len(rows), len(events)


def run_pipeline():
    print("=== Запуск ETL-пайплайна прогноза погоды ===")

    with get_connection() as conn:
        # 1. Получаем список активных дата-центров
        datacenters = get_active_datacenters(conn)
        if not datacenters:
            print("Внимание: нет активных площадок в таблице datacenters.")
            return

        print(f"Найдено активных ЦОД для опроса: {len(datacenters)}")

        # 2. Опрашиваем каждый ЦОД
        for dc_id, lat, lon in datacenters:
            print(f"\nЗапрос прогноза для {dc_id} (lat={lat}, lon={lon})...")
            try:
                # Клиент сам скачивает и возвращает готовые нормализованные данные
                forecast_records = fetch_weather_forecast(float(lat), float(lon), forecast_days=16)

                # Сохраняем в БД
                count, issues = save_checked_weather(conn, dc_id, forecast_records)
                print(f"  DQ: {issues} событий в журнале")
                print(f"✓ Успешно сохранено/обновлено {count} точек прогноза для {dc_id}")

            except Exception as e:
                # Ошибка одного ЦОД не ломает сбор для остальных
                print(f"✗ Ошибка при обработке {dc_id}: {e}")

    print("\n=== Пайплайн завершён ===")


if __name__ == "__main__":
    run_pipeline()
