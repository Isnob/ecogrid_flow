"""
Оркестратор ETL-пайплайна сбора метеопрогнозов для активных дата-центров.
"""

from collectors.open_meteo import fetch_weather_forecast
from db import get_connection, get_active_datacenters, save_weather_forecast


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
                count = save_weather_forecast(conn, dc_id, forecast_records)
                print(f"✓ Успешно сохранено/обновлено {count} точек прогноза для {dc_id}")

            except Exception as e:
                # Ошибка одного ЦОД не ломает сбор для остальных
                print(f"✗ Ошибка при обработке {dc_id}: {e}")

    print("\n=== Пайплайн завершён ===")


if __name__ == "__main__":
    run_pipeline()
