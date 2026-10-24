"""
Клиент для взаимодействия с Open-Meteo Weather Forecast API.
Отвечает за получение и парсинг сырого ответа в унифицированный список записей.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
import requests

OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Список метрик, согласованный в S2T
HOURLY_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "cloud_cover",
    "wind_speed_10m",
    "shortwave_radiation",
]


def fetch_weather_forecast(
    latitude: float,
    longitude: float,
    forecast_days: int = 16
) -> List[Tuple]:
    """
    Запрашивает прогноз погоды и возвращает нормализованный список кортежей:
    [(forecast_time, temperature_2m, relative_humidity_2m, cloud_cover, wind_speed_10m, shortwave_radiation), ...]
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "GMT",
        "forecast_days": forecast_days,
    }

    response = requests.get(OPEN_METEO_BASE_URL, params=params, timeout=10)
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
    # Тест для координат Хельсинки
    test_lat, test_lon = 60.1695, 24.9354
    print(f"Тестовый запрос и парсинг для lat={test_lat}, lon={test_lon}...")
    records = fetch_weather_forecast(test_lat, test_lon, forecast_days=2)
    print(f"✓ Успешно получено и нормализовано записей: {len(records)}")
    first_dt, first_temp, *_ = records[0]
    print(f"  Первая запись: время={first_dt}, температура={first_temp}°C")
