"""
Клиент для взаимодействия с ENTSO-E Transparency Platform API (Day-Ahead Prices, documentType A44).
Отвечает за получение и парсинг XML-ответа в унифицированный список записей.

Токен берётся из переменной окружения ENTSOE_API_TOKEN и передаётся в адресе запроса,
поэтому адрес запроса нигде не выводится и не попадает в текст исключений.
"""

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Tuple
import requests

ENTSOE_API_URL = "https://web-api.tp.entsoe.eu/api"

# EIC-коды энергозон MVP
BIDDING_ZONES: Dict[str, str] = {
    "DE-LU": "10Y1001A1001A82H",
    "FI": "10YFI-1--------U",
    "SE3": "10Y1001A1001A46L",
}

# Текст причины, с которым ENTSO-E отвечает, если цены за период ещё не опубликованы
NO_DATA_REASON_TEXT = "No matching data found"


def fetch_day_ahead_prices(
    bidding_zone: str,
    period_start: datetime,
    period_end: datetime,
) -> List[Tuple]:
    """
    Запрашивает цены Day-Ahead по энергозоне за период [period_start; period_end) в UTC
    и возвращает нормализованный список кортежей:
    [(bidding_zone, period_start, period_end, resolution, price, currency, price_unit), ...]
    ENTSO-E отдаёт сутки поставки целиком; если цены ещё не опубликованы — пустой список.
    Период может быть и в прошлом (архив для fallback и бэктеста), но не длиннее года за запрос.
    """
    token = os.getenv("ENTSOE_API_TOKEN")
    if not token:
        raise RuntimeError("Не задан токен ENTSO-E: переменная окружения ENTSOE_API_TOKEN")

    eic = BIDDING_ZONES[bidding_zone]
    params = {
        "securityToken": token,
        "documentType": "A44",
        "in_Domain": eic,
        "out_Domain": eic,
        "periodStart": _format_period(period_start),
        "periodEnd": _format_period(period_end),
    }

    try:
        response = requests.get(ENTSOE_API_URL, params=params, timeout=30)
    except requests.RequestException as e:
        # Текст исключения requests содержит адрес запроса вместе с токеном
        raise RuntimeError(f"Ошибка запроса к ENTSO-E ({bidding_zone}): {type(e).__name__}") from None

    # «Нет данных» приходит с HTTP 200, ошибки (неверный токен, лимит запросов) — с другим статусом.
    # У обоих один и тот же код причины 999, поэтому различаем их по статусу.
    if response.status_code != 200:
        raise RuntimeError(
            f"ENTSO-E вернул HTTP {response.status_code} для {bidding_zone}: {_reason_text(response.text)}"
        )

    return parse_day_ahead_prices(response.text, bidding_zone)


def parse_day_ahead_prices(xml_text: str, bidding_zone: str) -> List[Tuple]:
    """
    Разбирает XML ответа ENTSO-E (Publication_MarketDocument) в список кортежей
    (bidding_zone, period_start, period_end, resolution, price, currency, price_unit).

    Особенности формата:
    * curveType A03 — точки с той же ценой, что у предыдущей, в ответе пропускаются;
      пропуски восстанавливаются ценой предыдущей точки;
    * для DE-LU приходят два ряда: classificationSequence 1 — основной аукцион SDAC,
      2 — дополнительный аукцион; берётся только ряд 1.
    """
    root = ET.fromstring(xml_text)
    ns = _namespace(root)

    if root.tag.endswith("Acknowledgement_MarketDocument"):
        text = root.findtext(f"{ns}Reason/{ns}text") or ""
        if text.startswith(NO_DATA_REASON_TEXT):
            return []
        raise RuntimeError(f"ENTSO-E отклонил запрос для {bidding_zone}: {text}")

    records = []
    for series in root.findall(f"{ns}TimeSeries"):
        sequence = series.findtext(f"{ns}classificationSequence_AttributeInstanceComponent.position")
        if sequence not in (None, "1"):
            continue

        currency = series.findtext(f"{ns}currency_Unit.name")
        price_unit = series.findtext(f"{ns}price_Measure_Unit.name")

        for period in series.findall(f"{ns}Period"):
            resolution = period.findtext(f"{ns}resolution")
            step = _parse_resolution(resolution)
            start = datetime.fromisoformat(period.findtext(f"{ns}timeInterval/{ns}start"))
            end = datetime.fromisoformat(period.findtext(f"{ns}timeInterval/{ns}end"))
            slots = int((end - start) / step)

            prices = {
                int(point.findtext(f"{ns}position")): Decimal(point.findtext(f"{ns}price.amount"))
                for point in period.findall(f"{ns}Point")
            }

            price = None
            for position in range(1, slots + 1):
                price = prices.get(position, price)
                if price is None:
                    continue
                slot_start = start + step * (position - 1)
                records.append((
                    bidding_zone,
                    slot_start,
                    slot_start + step,
                    resolution,
                    price,
                    currency,
                    price_unit,
                ))

    return records


def _parse_resolution(value: str) -> timedelta:
    """Шаг ряда в формате ISO 8601: PT15M, PT60M, PT1H и т. п."""
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", value)
    if not match or not any(match.groups()):
        raise ValueError(f"Неизвестный шаг временного ряда ENTSO-E: {value}")
    hours, minutes = (int(group or 0) for group in match.groups())
    return timedelta(hours=hours, minutes=minutes)


def _reason_text(xml_text: str) -> str:
    """Текст причины из Acknowledgement_MarketDocument; адреса запроса и токена в нём нет."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return "ответ не в формате XML"
    ns = _namespace(root)
    return root.findtext(f"{ns}Reason/{ns}text") or "причина не указана"


def _namespace(root: ET.Element) -> str:
    return root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""


def _format_period(value: datetime) -> str:
    """ENTSO-E принимает время в UTC в формате yyyyMMddHHmm."""
    if value.tzinfo is None:
        raise ValueError("Время периода должно быть с часовым поясом (UTC)")
    return value.astimezone(timezone.utc).strftime("%Y%m%d%H%M")


if __name__ == "__main__":
    # Тест: цены на ближайшие сутки по всем зонам MVP
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    for zone in BIDDING_ZONES:
        print(f"Тестовый запрос цен Day-Ahead для {zone}...")
        records = fetch_day_ahead_prices(zone, now, now + timedelta(days=1))
        if not records:
            print("  Цены за период ещё не опубликованы")
            continue
        _, first_start, _, resolution, first_price, currency, unit = records[0]
        print(f"✓ Получено интервалов: {len(records)} (шаг {resolution})")
        print(f"  Первый интервал: {first_start}, цена={first_price} {currency}/{unit}")
