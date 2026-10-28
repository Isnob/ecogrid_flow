"""
Оркестратор ETL-пайплайна сбора цен Day-Ahead ENTSO-E по энергозонам MVP.

Без аргументов загружает сегодняшние и завтрашние сутки поставки.
С --start-date / --end-date загружает архив за период (Backfill), частями не длиннее года.
Когда запускать загрузку, решает планировщик (scheduler.py) с помощью missing_zones_for_tomorrow().
"""

import argparse
import sys
from datetime import date, datetime, time, timedelta
from typing import Optional, Set
from zoneinfo import ZoneInfo
from collectors.entso_e_days_ahead import BIDDING_ZONES, fetch_day_ahead_prices
from db import get_connection, get_zones_with_prices, save_day_ahead_prices

# Сутки поставки на рынке Day-Ahead считаются по центральноевропейскому времени
MARKET_TZ = ZoneInfo("Europe/Brussels")

# ENTSO-E отдаёт за один запрос не больше года
MAX_CHUNK_DAYS = 365


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
                    else:
                        count = save_day_ahead_prices(conn, records)
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
        zones = get_zones_with_prices(conn, _market_midnight(tomorrow), _market_midnight(tomorrow + timedelta(days=1)))
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
