"""
Оркестратор разовой/пакетной загрузки исторического метеоархива для активных ЦОД.
Используется для начального бэкфилла (Backfill) и подготовки данных для EDA и бэктеста.
"""

import argparse
import os
import sys
from datetime import datetime
from collectors.open_meteo_historical import fetch_historical_weather
from db import get_connection, get_active_datacenters, save_historical_weather


def run_pipeline(start_date: str, end_date: str):
    print("=== Запуск выгрузки архива погоды Open-Meteo ===")
    print(f"Период выборки: с {start_date} по {end_date}")

    with get_connection() as conn:
        datacenters = get_active_datacenters(conn)
        if not datacenters:
            print("Внимание: нет активных площадок в таблице datacenters.")
            return

        print(f"Найдено активных ЦОД: {len(datacenters)}")

        total_saved = 0
        for dc_id, lat, lon in datacenters:
            print(f"\nЗапрос архива для {dc_id} (lat={lat}, lon={lon})...")
            try:
                t0 = datetime.now()
                records = fetch_historical_weather(
                    float(lat),
                    float(lon),
                    start_date=start_date,
                    end_date=end_date,
                )
                fetch_time = (datetime.now() - t0).total_seconds()
                print(f"  Скачано и нормализовано {len(records)} записей за {fetch_time:.2f} сек.")

                count = save_historical_weather(conn, dc_id, records)
                print(f"✓ Успешно сохранено/обновлено в БД: {count} строк для {dc_id}")
                total_saved += count
            except Exception as e:
                print(f"✗ Ошибка при обработке {dc_id}: {e}", file=sys.stderr)

    print(f"\n=== Выгрузка архива завершена. Всего сохранено строк: {total_saved} ===")


def main():
    parser = argparse.ArgumentParser(description="ETL загрузка исторического метеоархива Open-Meteo.")
    parser.add_argument(
        "--start-date",
        type=str,
        default=os.getenv("START_DATE", "2023-10-01"),
        help="Начальная дата в формате YYYY-MM-DD (по умолчанию 2023-10-01)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=os.getenv("END_DATE", "2026-10-23"),
        help="Конечная дата в формате YYYY-MM-DD (по умолчанию 2026-10-23)",
    )

    args = parser.parse_args()
    run_pipeline(args.start_date, args.end_date)


if __name__ == "__main__":
    main()
