# Тестовые фикстуры ответов ENTSO-E (Day-Ahead Prices)

В этой директории сохранены эталонные XML-ответы от ENTSO-E Transparency Platform API.
Они используются для запуска юнит-тестов парсера, проверки представления `v_entsoe_prices_hourly`
и моделирования сценариев без обращения к внешнему сетевому API.

## Состав фикстур

| Файл | Зона | Период (рыночный) | Описание |
| :--- | :---: | :---: | :--- |
| [`de_lu_pt15m_two_series.xml`](de_lu_pt15m_two_series.xml) | `DE-LU` | 2025-11-15 … 2025-11-16 | DE-LU, 15-минутный шаг (PT15M, SDAC после 01.10.2025). Содержит два TimeSeries (classificationSequence 1 и 2). |
| [`fi_pt15m_with_negative_prices.xml`](fi_pt15m_with_negative_prices.xml) | `FI` | 2025-10-19 … 2025-10-20 | FI, 15-минутный шаг (PT15M) с отрицательными ценами и сжатием одинаковых точек (curveType A03). |
| [`se3_pt15m_standard.xml`](se3_pt15m_standard.xml) | `SE3` | 2025-11-15 … 2025-11-16 | SE3, стандартные сутки с шагом PT15M (96 точек). |
| [`fi_pt60m_historical.xml`](fi_pt60m_historical.xml) | `FI` | 2024-06-12 … 2024-06-13 | FI, исторический почасовой шаг PT60M (24 точки, для проверки бэкфилла за 3 года). |
| [`de_lu_dst_winter_25h.xml`](de_lu_dst_winter_25h.xml) | `DE-LU` | 2024-10-27 … 2024-10-28 | DE-LU, переход на зимнее время (длинные сутки 25 часов, 25 почасовых интервалов). |
| [`fi_dst_summer_23h.xml`](fi_dst_summer_23h.xml) | `FI` | 2025-03-30 … 2025-03-31 | FI, переход на летнее время (короткие сутки 23 часа, 23 интервала по 1 ч). |
| [`acknowledgement_no_data.xml`](acknowledgement_no_data.xml) | `DE-LU` | 2028-01-01 … 2028-01-02 | Ответ Acknowledgement_MarketDocument: цены за период ещё не опубликованы (Reason: No matching data found). |

## Обновление фикстур

Для повторной выгрузки или добавления новых сценариев используется скрипт:
```bash
python tests/fetch_entsoe_fixtures.py
```
