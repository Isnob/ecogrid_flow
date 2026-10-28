"""
Фоновый планировщик регулярного сбора данных.
* Прогноз погоды (почасовой) — загружается заново при старте и далее каждые
  WEATHER_UPDATE_INTERVAL_HOURS часов (по умолчанию 3).
* Цены Day-Ahead (15-минутные) — загружаются при старте и далее по событию: с момента
  публикации (около 13:00 CET) каждые 15 минут, пока не появятся цены на завтра,
  затем до следующей публикации.
"""

import os
import signal
import sys
import time
from datetime import datetime, time as clock, timedelta, timezone
import run_prices
import run_weather

running = True


def handle_shutdown(signum, frame):
    global running
    print("\n[Scheduler] Получен сигнал остановки контейнера. Завершаем работу...")
    running = False


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# Как часто заново загружать прогноз погоды, в часах (сам прогноз почасовой)
WEATHER_UPDATE_INTERVAL_HOURS = int(os.getenv("WEATHER_UPDATE_INTERVAL_HOURS", "3"))

# Результаты аукциона на завтра публикуются около 12:45–13:00 CET
PRICES_PUBLICATION_TIME = clock(13, 0)
# Пока цен на завтра нет, повторяем загрузку цен с таким интервалом
PRICES_RETRY_INTERVAL = timedelta(minutes=15)
# Если к этому времени цен на завтра нет, расчёт на завтра уйдёт в Fallback (DR-01)
PRICES_FALLBACK_DEADLINE = clock(14, 30)


def next_prices_attempt(now: datetime, tomorrow_loaded: bool) -> datetime:
    """
    Время следующей загрузки цен (now — по рыночному времени):
    * цены на завтра уже есть — завтра в момент публикации;
    * ещё не время публикации — сегодня в момент публикации;
    * публикация уже должна была пройти — через PRICES_RETRY_INTERVAL.
    """
    publication_today = datetime.combine(now.date(), PRICES_PUBLICATION_TIME, tzinfo=run_prices.MARKET_TZ)
    if tomorrow_loaded:
        return publication_today + timedelta(days=1)
    if now < publication_today:
        return publication_today
    return now + PRICES_RETRY_INTERVAL


def run_prices_job() -> datetime:
    """Загружает цены за сегодня и завтра и возвращает время следующей загрузки."""
    run_prices.run_pipeline()

    missing = run_prices.missing_zones_for_tomorrow()
    now = datetime.now(run_prices.MARKET_TZ)
    if missing and now.time() >= PRICES_FALLBACK_DEADLINE:
        print(
            f"⚠ Цен на завтра к {PRICES_FALLBACK_DEADLINE:%H:%M} CET нет по зонам: {', '.join(sorted(missing))}",
            file=sys.stderr,
        )
    return next_prices_attempt(now, not missing)


def main():
    print(f"[Scheduler] Старт планировщика ETL. Прогноз погоды обновляется каждые {WEATHER_UPDATE_INTERVAL_HOURS} ч, цены — после публикации.")

    next_weather = time.monotonic()
    next_prices = datetime.now(timezone.utc)

    while running:
        if time.monotonic() >= next_weather:
            try:
                run_weather.run_pipeline()
            except Exception as e:
                print(f"[Scheduler] Непредвиденная ошибка в пайплайне погоды: {e}")
            next_weather = time.monotonic() + WEATHER_UPDATE_INTERVAL_HOURS * 3600
            print(f"[Scheduler] Следующее обновление прогноза погоды через {WEATHER_UPDATE_INTERVAL_HOURS} ч")

        if running and datetime.now(timezone.utc) >= next_prices:
            try:
                next_prices = run_prices_job()
            except Exception as e:
                print(f"[Scheduler] Непредвиденная ошибка в пайплайне цен: {e}")
                next_prices = datetime.now(timezone.utc) + PRICES_RETRY_INTERVAL
            print(f"[Scheduler] Следующая загрузка цен: {next_prices.astimezone(run_prices.MARKET_TZ):%Y-%m-%d %H:%M %Z}")

        # Проверяем расписание короткими шагами для быстрого отклика на остановку контейнера
        time.sleep(5)

    print("[Scheduler] Планировщик остановлен.")


if __name__ == "__main__":
    main()
