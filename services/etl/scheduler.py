"""
Фоновый планировщик регулярного сбора метеоданных.
Запускает сбор при старте и далее с заданным интервалом (по умолчанию раз в 3 часа).
"""

import os
import signal
import time
from run_weather import run_pipeline

running = True


def handle_shutdown(signum, frame):
    global running
    print("\n[Scheduler] Получен сигнал остановки контейнера. Завершаем работу...")
    running = False


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# Интервал в часах (по умолчанию 3 часа)
INTERVAL_HOURS = int(os.getenv("WEATHER_INTERVAL_HOURS", "3"))
INTERVAL_SECONDS = INTERVAL_HOURS * 3600


def main():
    print(f"[Scheduler] Старт планировщика ETL. Интервал обновления: {INTERVAL_HOURS} ч.")

    while running:
        try:
            run_pipeline()
        except Exception as e:
            print(f"[Scheduler] Непредвиденная ошибка в пайплайне: {e}")

        if not running:
            break

        print(f"[Scheduler] Ожидание следующего запуска через {INTERVAL_HOURS} ч...")

        # Спим короткими шагами по 5 секунд для быстрого отклика на остановку контейнера
        for _ in range(INTERVAL_SECONDS // 5):
            if not running:
                break
            time.sleep(5)

    print("[Scheduler] Планировщик остановлен.")


if __name__ == "__main__":
    main()
