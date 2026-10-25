"""
Клиент для взаимодействия с Open-Meteo Historical Weather (Archive) API.
Отвечает за выгрузку исторического архива метеоданных для ЦОД.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
import requests

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Список метрик, согласованный в S2T и PreColumns.md
HOURLY_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "cloud_cover",
    "wind_speed_10m",
    "shortwave_radiation",
]


def fetch_historical_weather(
    latitude: float,
    longitude: float,
    start_date: str = "2023-10-01",
    end_date: str = "2026-10-23",
) -> List[Tuple]:
    """
    Запрашивает архив метеоданных за указанный период (YYYY-MM-DD)
    и возвращает нормализованный список кортежей:
    [(observed_at, temperature_2m, relative_humidity_2m, cloud_cover, wind_speed_10m, shortwave_radiation), ...]
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "GMT",
    }

    response = requests.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=30)
    response.raise_for_status()
    data: Dict[str, Any] = response.json()

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    humidities = hourly.get("relative_humidity_2m", [])
    clouds = hourly.get("cloud_cover", [])
    winds = hourly.get("wind_speed_10m", [])
    radiations = hourly.get("shortwave_radiation", [])

    records = []
    for t_str, temp, hum, cloud, wind, rad in zip(times, temps, humidities, clouds, winds, radiations):
        dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
        records.append((
            dt,
            temp,
            hum,
            cloud,
            wind,
            rad
        ))

    return records


if __name__ == "__main__":
    # Тест для координат Хельсинки за небольшой диапазон
    test_lat, test_lon = 60.1695, 24.9354
    print(f"Тестовый запрос к архиву для lat={test_lat}, lon={test_lon} (2023-10-01 - 2023-10-02)...")
    records = fetch_historical_weather(test_lat, test_lon, start_date="2023-10-01", end_date="2023-10-02")
    print(f"✓ Успешно получено записей архива: {len(records)}")
    first_dt, first_temp, *_ = records[0]
    print(f"  Первая запись: время={first_dt}, темп={first_temp}°C")
