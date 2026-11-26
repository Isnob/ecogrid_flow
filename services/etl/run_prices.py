"""
Оркестратор ETL-пайплайна сбора цен Day-Ahead ENTSO-E по энергозонам MVP.

Без аргументов загружает сегодняшние и завтрашние сутки поставки.
С --start-date / --end-date загружает архив за период (Backfill), частями не длиннее года.
Когда запускать загрузку, решает планировщик (scheduler.py) с помощью missing_zones_for_tomorrow().
"""

import argparse
import sys
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Set
from zoneinfo import ZoneInfo
from collectors.entso_e_days_ahead import BIDDING_ZONES, fetch_day_ahead_prices
from db import get_connection

from decimal import Decimal, InvalidOperation
from uuid import uuid4
from psycopg.types.json import Jsonb

UTC = timezone.utc
STEPS = {"PT60M": timedelta(hours=1), "PT15M": timedelta(minutes=15)}

# Сутки поставки на рынке Day-Ahead считаются по центральноевропейскому времени
MARKET_TZ = ZoneInfo("Europe/Brussels")

# ENTSO-E отдаёт за один запрос не больше года
MAX_CHUNK_DAYS = 365


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


def price_errors(row):
    if not isinstance(row, (tuple, list)) or len(row) != 7:
        return ["invalid_row_shape"]
    zone, start, end, resolution, price, currency, unit = row
    errors = []
    if zone not in {"DE-LU", "FI", "SE3"}:
        errors.append("invalid_zone")
    if not number(price, -500, 4000):
        errors.append("price_out_of_range")
    if currency != "EUR":
        errors.append("currency_not_eur")
    if unit != "MWH":
        errors.append("unit_not_mwh")
    if resolution not in STEPS:
        errors.append("invalid_resolution")
    elif not aware(start) or not aware(end):
        errors.append("invalid_timestamp")
    elif (end - start != STEPS[resolution] or start.second or start.microsecond
          or start.minute % (15 if resolution == "PT15M" else 60)):
        errors.append("invalid_interval")
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


def day_bounds(day):
    start = datetime.combine(day, time.min, MARKET_TZ).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, MARKET_TZ).astimezone(UTC)
    return start, end


def grid(start, end, step):
    while start < end:
        yield start
        start += step


def prepare_prices(records, zone, start, end, existing=()):
    """Fill bounded gaps up to one hour from original endpoints."""
    valid, events = validate(records, price_errors, lambda r: (r[0], r[1], r[3]))
    originals = {(r[0], r[1], r[3]): tuple(r) for r in existing if not price_errors(r)}
    originals.update({(r[0], r[1], r[3]): r for r in valid})
    result = {(r[0], r[1], r[3]): r + (None,) for r in valid}
    resolutions = {r[3] for r in records if isinstance(r, (tuple, list)) and len(r) == 7 and r[3] in STEPS}
    if not resolutions:
        events.append(event("range_unfilled_no_resolution", {"start": start, "end": end}))
    for resolution in sorted(resolutions):
        step = STEPS[resolution]
        slots = list(grid(start, end, step))
        i = 0
        while i < len(slots):
            if (zone, slots[i], resolution) in originals:
                i += 1
                continue
            first = i
            while i < len(slots) and (zone, slots[i], resolution) not in originals:
                i += 1
            left = originals.get((zone, slots[first - 1], resolution)) if first else None
            right = originals.get((zone, slots[i], resolution)) if i < len(slots) else None
            gap = slots[first:i]
            fill = left is not None and right is not None and len(gap) * step <= timedelta(hours=1)
            value = ((Decimal(str(left[4])) + Decimal(str(right[4]))) / 2).quantize(Decimal("0.01")) if fill else None
            for stamp in gap:
                payload = {"zone": zone, "period_start": stamp, "resolution": resolution, "gap_intervals": len(gap)}
                if fill:
                    result[(zone, stamp, resolution)] = (zone, stamp, stamp + step, resolution, value, "EUR", "MWH", "boundary_mean")
                    events.append(event("gap_filled_boundary_mean", payload))
                else:
                    events.append(event("gap_unfilled", payload))
    return list(result.values()), events


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


def save_checked_prices(conn, zone, records, start, end):
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """SELECT bidding_zone, period_start, period_end, resolution, price, currency, price_unit
               FROM entsoe_day_ahead_prices
               WHERE bidding_zone = %s AND imputation_method IS NULL
                 AND period_start >= %s AND period_start < %s""",
            (zone, start, end))
        history = cur.fetchall()
        rows, events = prepare_prices(records, zone, start, end, history)
        write_events(cur, "prices", zone, events)
        cur.executemany(
            """INSERT INTO entsoe_day_ahead_prices
               (bidding_zone, period_start, period_end, resolution, price, currency, price_unit, imputation_method)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (bidding_zone, period_start, resolution) DO UPDATE SET
                 period_end = EXCLUDED.period_end, price = EXCLUDED.price,
                 currency = EXCLUDED.currency, price_unit = EXCLUDED.price_unit,
                 imputation_method = EXCLUDED.imputation_method, retrieved_at = NOW()
               WHERE EXCLUDED.imputation_method IS NULL
                  OR entsoe_day_ahead_prices.imputation_method IS NOT NULL""", rows,
        )
    return len(rows), len(events)


def run_pipeline(start_date: Optional[date] = None, end_date: Optional[date] = None):
    """
    Загружает цены за диапазон дат [start_date; end_date] включительно — любой длины.
    Без аргументов — за сегодня и завтра по рыночному времени.
    """
    today = datetime.now(MARKET_TZ).date()
    start_date = start_date or today
    end_date = end_date or today + timedelta(days=1)

    print("=== Запуск ETL-пайплайна цен Day-Ahead ENTSO-E ===")
    print(f"Сутки поставки: с {start_date} по {end_date}")

    with get_connection() as conn:
        total_saved = 0
        for zone in BIDDING_ZONES:
            chunk_start = start_date
            while chunk_start <= end_date:
                chunk_end = min(chunk_start + timedelta(days=MAX_CHUNK_DAYS - 1), end_date)
                print(f"\nЗапрос цен для {zone}: {chunk_start} — {chunk_end}...")
                try:
                    records = fetch_day_ahead_prices(
                        zone,
                        _market_midnight(chunk_start),
                        _market_midnight(chunk_end + timedelta(days=1)),
                    )
                    if not records:
                        print("  Цены за период ещё не опубликованы")
                    count, issues = save_checked_prices(conn, zone, records, _market_midnight(chunk_start).astimezone(UTC), _market_midnight(chunk_end + timedelta(days=1)).astimezone(UTC))
                    print(f"  DQ: {issues} событий в журнале")
                    print(f"✓ Успешно сохранено/обновлено {count} интервалов для {zone}")
                    total_saved += count
                except Exception as e:
                    # Ошибка одной зоны не ломает сбор для остальных
                    print(f"✗ Ошибка при обработке {zone}: {e}", file=sys.stderr)
                chunk_start = chunk_end + timedelta(days=1)

    print(f"\n=== Пайплайн цен завершён. Всего сохранено интервалов: {total_saved} ===")


def missing_zones_for_tomorrow() -> Set[str]:
    """Энергозоны, по которым в БД ещё нет цен на завтрашние сутки поставки."""
    tomorrow = datetime.now(MARKET_TZ).date() + timedelta(days=1)
    with get_connection() as conn:
        start = _market_midnight(tomorrow)
        end = _market_midnight(tomorrow + timedelta(days=1))
        with conn.cursor() as cur:
            cur.execute(
                """SELECT bidding_zone FROM v_entsoe_prices_hourly
                   WHERE hour_start >= %s AND hour_start < %s AND NOT is_estimated
                   GROUP BY bidding_zone
                   HAVING COUNT(*) = EXTRACT(EPOCH FROM (%s::timestamptz - %s::timestamptz)) / 3600""",
                (start, end, end, start),
            )
            zones = {row[0] for row in cur.fetchall()}
    return set(BIDDING_ZONES) - zones


def _market_midnight(day: date) -> datetime:
    """Начало суток поставки (00:00 по рыночному времени) с часовым поясом."""
    return datetime.combine(day, time.min, tzinfo=MARKET_TZ)


def main():
    parser = argparse.ArgumentParser(description="ETL загрузка цен Day-Ahead ENTSO-E.")
    parser.add_argument("--start-date", type=date.fromisoformat, help="Первые сутки поставки, YYYY-MM-DD")
    parser.add_argument("--end-date", type=date.fromisoformat, help="Последние сутки поставки, YYYY-MM-DD")

    args = parser.parse_args()
    run_pipeline(args.start_date, args.end_date)


if __name__ == "__main__":
    main()
