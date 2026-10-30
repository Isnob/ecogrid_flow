"""
Скрипт выгрузки эталонных XML-фикстур от ENTSO-E Transparency Platform API.

Скачивает сырые ответы API для различных сценариев (PT15M, PT60M, переходы DST,
отрицательные цены, ответ «данные не найдены») и сохраняет их в tests/fixtures/entsoe/.

Использование:
    python tests/fetch_entsoe_fixtures.py                 # скачать стандартный тестовый набор
    python tests/fetch_entsoe_fixtures.py --zone FI --start 2025-10-15 --end 2025-10-16 --name custom_fi
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
import requests
from dotenv import load_dotenv

# Пути проекта
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "entsoe"

ENTSOE_API_URL = "https://web-api.tp.entsoe.eu/api"

# EIC-коды энергозон MVP
BIDDING_ZONES: Dict[str, str] = {
    "DE-LU": "10Y1001A1001A82H",
    "FI": "10YFI-1--------U",
    "SE3": "10Y1001A1001A46L",
}

# Стандартный эталонный набор сценариев для тестирования
STANDARD_FIXTURES = [
    {
        "filename": "de_lu_pt15m_two_series.xml",
        "zone": "DE-LU",
        "start": "2025-11-15T00:00:00+01:00",
        "end": "2025-11-16T00:00:00+01:00",
        "description": "DE-LU, 15-минутный шаг (PT15M, SDAC после 01.10.2025). Содержит два TimeSeries (classificationSequence 1 и 2).",
    },
    {
        "filename": "fi_pt15m_with_negative_prices.xml",
        "zone": "FI",
        "start": "2025-10-19T00:00:00+02:00",
        "end": "2025-10-20T00:00:00+02:00",
        "description": "FI, 15-минутный шаг (PT15M) с отрицательными ценами и сжатием одинаковых точек (curveType A03).",
    },
    {
        "filename": "se3_pt15m_standard.xml",
        "zone": "SE3",
        "start": "2025-11-15T00:00:00+01:00",
        "end": "2025-11-16T00:00:00+01:00",
        "description": "SE3, стандартные сутки с шагом PT15M (96 точек).",
    },
    {
        "filename": "fi_pt60m_historical.xml",
        "zone": "FI",
        "start": "2024-06-12T00:00:00+02:00",
        "end": "2024-06-13T00:00:00+02:00",
        "description": "FI, исторический почасовой шаг PT60M (24 точки, для проверки бэкфилла за 3 года).",
    },
    {
        "filename": "de_lu_dst_winter_25h.xml",
        "zone": "DE-LU",
        "start": "2024-10-27T00:00:00+02:00",
        "end": "2024-10-28T00:00:00+01:00",
        "description": "DE-LU, переход на зимнее время (длинные сутки 25 часов, 25 почасовых интервалов).",
    },
    {
        "filename": "fi_dst_summer_23h.xml",
        "zone": "FI",
        "start": "2025-03-30T00:00:00+01:00",
        "end": "2025-03-31T00:00:00+02:00",
        "description": "FI, переход на летнее время (короткие сутки 23 часа, 23 интервала по 1 ч).",
    },
    {
        "filename": "acknowledgement_no_data.xml",
        "zone": "DE-LU",
        # Заведомо далекая будущая дата
        "start": "2028-01-01T00:00:00+01:00",
        "end": "2028-01-02T00:00:00+01:00",
        "description": "Ответ Acknowledgement_MarketDocument: цены за период ещё не опубликованы (Reason: No matching data found).",
    },
]


def load_token() -> str:
    """Загружает токен ENTSOE_API_TOKEN из окружения или .env файла."""
    load_dotenv(PROJECT_ROOT / ".env")
    token = os.getenv("ENTSOE_API_TOKEN")
    if not token:
        print("Ошибка: переменная ENTSOE_API_TOKEN не найдена в .env и в окружении.", file=sys.stderr)
        sys.exit(1)
    return token.strip()


def format_utc_for_entsoe(dt: datetime) -> str:
    """Форматирует datetime в yyyyMMddHHmm (UTC) для ENTSO-E API."""
    if dt.tzinfo is None:
        raise ValueError("Объект datetime должен содержать часовой пояс.")
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M")


def sanitize_xml(xml_text: str) -> str:
    """
    Маскирует персональные/чувствительные данные (например, EIC пользователя в mRID получателя),
    чтобы безопасно хранить фикстуру в репозитории.
    """
    # Маскируем mRID получателя в Acknowledgement_MarketDocument, если присутствует
    sanitized = re.sub(
        r"(<receiver_MarketParticipant\.mRID[^>]*>)([^<]+)(</receiver_MarketParticipant\.mRID>)",
        r"\g<1>10X1001A1001A99Z\g<3>",
        xml_text,
    )
    return sanitized


def fetch_raw_xml(token: str, zone: str, start: datetime, end: datetime) -> str:
    """Выполняет прямой запрос к ENTSO-E API и возвращает сырой текст XML."""
    eic = BIDDING_ZONES[zone]
    params = {
        "securityToken": token,
        "documentType": "A44",
        "in_Domain": eic,
        "out_Domain": eic,
        "periodStart": format_utc_for_entsoe(start),
        "periodEnd": format_utc_for_entsoe(end),
    }

    response = requests.get(ENTSOE_API_URL, params=params, timeout=30)
    # Acknowledgement с отсутствием данных приходит со статусом 200
    if response.status_code != 200 and not response.text.startswith("<?xml"):
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")

    return sanitize_xml(response.text)


def update_fixtures_readme(manifest: list):
    """Генерирует и сохраняет README.md в папке фикстур с описанием файлов."""
    readme_path = FIXTURES_DIR / "README.md"
    lines = [
        "# Тестовые фикстуры ответов ENTSO-E (Day-Ahead Prices)",
        "",
        "В этой директории сохранены эталонные XML-ответы от ENTSO-E Transparency Platform API.",
        "Они используются для запуска юнит-тестов парсера, проверки представления `v_entsoe_prices_hourly`",
        "и моделирования сценариев без обращения к внешнему сетевому API.",
        "",
        "## Состав фикстур",
        "",
        "| Файл | Зона | Период (рыночный) | Описание |",
        "| :--- | :---: | :---: | :--- |",
    ]
    for item in manifest:
        fn = item["filename"]
        zone = item.get("zone", "-")
        period = f"{item['start'][:10]} … {item['end'][:10]}" if "start" in item else "-"
        desc = item["description"]
        lines.append(f"| [`{fn}`]({fn}) | `{zone}` | {period} | {desc} |")

    lines.extend([
        "",
        "## Обновление фикстур",
        "",
        "Для повторной выгрузки или добавления новых сценариев используется скрипт:",
        "```bash",
        "python tests/fetch_entsoe_fixtures.py",
        "```",
    ])
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✓ Документация фикстур обновлена: {readme_path.relative_to(PROJECT_ROOT)}")


def main():
    parser = argparse.ArgumentParser(description="Выгрузка эталонных XML-фикстур ENTSO-E")
    parser.add_argument("--zone", choices=list(BIDDING_ZONES.keys()), help="Энергозона (DE-LU, FI, SE3)")
    parser.add_argument("--start", help="Начало периода (ISO 8601 с часовым поясом, например 2025-11-15T00:00:00+01:00)")
    parser.add_argument("--end", help="Конец периода (ISO 8601 с часовым поясом)")
    parser.add_argument("--filename", help="Имя сохраняемого XML-файла в tests/fixtures/entsoe/")
    parser.add_argument("--description", default="Пользовательская фикстура", help="Описание для README")

    args = parser.parse_args()
    token = load_token()
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    if args.zone and args.start and args.end:
        filename = args.filename or f"{args.zone.lower().replace('-', '_')}_{args.start[:10]}.xml"
        tasks = [{
            "filename": filename,
            "zone": args.zone,
            "start": args.start,
            "end": args.end,
            "description": args.description,
        }]
    else:
        tasks = STANDARD_FIXTURES

    manifest = []
    print(f"=== Загрузка фикстур ENTSO-E ({len(tasks)} файлов) ===")
    for task in tasks:
        filepath = FIXTURES_DIR / task["filename"]
        start_dt = datetime.fromisoformat(task["start"])
        end_dt = datetime.fromisoformat(task["end"])
        print(f"Запрос для {task['filename']} ({task['zone']}: {task['start']} -> {task['end']})...")

        try:
            xml_text = fetch_raw_xml(token, task["zone"], start_dt, end_dt)
            filepath.write_text(xml_text, encoding="utf-8")
            manifest.append(task)
            print(f"  ✓ Сохранено: {filepath.relative_to(PROJECT_ROOT)} ({len(xml_text)} байт)")
        except Exception as e:
            print(f"  ✗ Ошибка при скачивании {task['filename']}: {e}", file=sys.stderr)

    if manifest:
        update_fixtures_readme(manifest)
    print("\nГотово!")


if __name__ == "__main__":
    main()
