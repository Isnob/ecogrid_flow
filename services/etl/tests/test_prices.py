from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest
import requests

from collectors import entso_e_days_ahead as prices

UTC = timezone.utc
START = datetime(2025, 11, 14, 23, tzinfo=UTC)
END = START + timedelta(days=1)


@pytest.mark.parametrize('name,zone,resolution,count,start,end,first', [
    ('de_lu_pt15m_two_series.xml', 'DE-LU', 'PT15M', 96, '2025-11-14T23:00+00:00', '2025-11-15T23:00+00:00', '85.67'),
    ('fi_pt15m_with_negative_prices.xml', 'FI', 'PT15M', 96, '2025-10-18T22:00+00:00', '2025-10-19T22:00+00:00', '3.3'),
    ('se3_pt15m_standard.xml', 'SE3', 'PT15M', 96, '2025-11-14T23:00+00:00', '2025-11-15T23:00+00:00', '29.62'),
    ('fi_pt60m_historical.xml', 'FI', 'PT60M', 24, '2024-06-11T22:00+00:00', '2024-06-12T22:00+00:00', '32.4'),
    ('de_lu_dst_winter_25h.xml', 'DE-LU', 'PT60M', 25, '2024-10-26T22:00+00:00', '2024-10-27T23:00+00:00', '92.22'),
    ('fi_dst_summer_23h.xml', 'FI', 'PT60M', 23, '2025-03-29T23:00+00:00', '2025-03-30T22:00+00:00', '5.96'),
])
def test_real_price_days(xml_fixture, name, zone, resolution, count, start, end, first):
    rows = prices.parse_day_ahead_prices(xml_fixture(name), zone)
    assert len(rows) == count
    assert rows[0][1] == datetime.fromisoformat(start)
    assert rows[-1][2] == datetime.fromisoformat(end)
    assert rows[0][4] == Decimal(first)
    step = timedelta(minutes=15 if resolution == 'PT15M' else 60)
    assert len({row[1] for row in rows}) == count
    for i, row in enumerate(rows):
        assert row[0] == zone
        assert row[1] == datetime.fromisoformat(start) + step * i
        assert row[2] - row[1] == step
        assert row[1].utcoffset() == timedelta(0)
        assert row[3] == resolution
        assert isinstance(row[4], Decimal)
        assert row[5:] == ('EUR', 'MWH')


def test_a03_gaps(xml_fixture):
    xml = xml_fixture('fi_pt15m_with_negative_prices.xml')
    root = ET.fromstring(xml)
    points = root.findall('.//{*}Point')
    explicit = {int(p.findtext('{*}position')): Decimal(p.findtext('{*}price.amount')) for p in points}
    rows = prices.parse_day_ahead_prices(xml, 'FI')
    missing = sorted(set(range(1, 97)) - explicit.keys())
    assert missing, 'Fixture must exercise compressed A03 points'
    assert min(row[4] for row in rows) == Decimal("1.5")
    for position, value in explicit.items():
        assert rows[position - 1][4] == value
    for position in missing:
        previous = max(p for p in explicit if p < position)
        assert rows[position - 1][4] == explicit[previous]


def test_de_lu_ignores_secondary_series_in_any_order(xml_fixture):
    root = ET.fromstring(xml_fixture('de_lu_pt15m_two_series.xml'))
    series = root.findall('{*}TimeSeries')
    assert len(series) == 2
    secondary = next(s for s in series if s.findtext('{*}classificationSequence_AttributeInstanceComponent.position') == '2')
    for value in secondary.findall('.//{*}price.amount'):
        value.text = '9999'
    for series_order in (series, list(reversed(series))):
        for series_node in root.findall('{*}TimeSeries'):
            root.remove(series_node)
        root.extend(series_order)
        rows = prices.parse_day_ahead_prices(ET.tostring(root, encoding='unicode'), 'DE-LU')
        assert len(rows) == 96
        assert rows[0][4] == Decimal('85.67')
        assert all(r[4] != 9999 for r in rows)


def test_no_data_document(xml_fixture):
    assert prices.parse_day_ahead_prices(xml_fixture('acknowledgement_no_data.xml'), 'DE-LU') == []


def test_fetch_request_and_real_response(monkeypatch, xml_fixture):
    monkeypatch.setenv('ENTSOE_API_TOKEN', 'test-token-not-a-secret')
    get = Mock(return_value=Mock(status_code=200, text=xml_fixture('se3_pt15m_standard.xml')))
    monkeypatch.setattr(prices.requests, 'get', get)
    rows = prices.fetch_day_ahead_prices('SE3', START, END)
    assert len(rows) == 96
    get.assert_called_once_with(prices.ENTSOE_API_URL, params={
        'securityToken': 'test-token-not-a-secret', 'documentType': 'A44',
        'in_Domain': '10Y1001A1001A46L', 'out_Domain': '10Y1001A1001A46L',
        'periodStart': '202511142300', 'periodEnd': '202511152300',
    }, timeout=30)


@pytest.mark.parametrize('status', [200, 401])
def test_no_data_and_http_error_are_distinct(monkeypatch, xml_fixture, status):
    monkeypatch.setenv('ENTSOE_API_TOKEN', 'fake-token')
    monkeypatch.setattr(prices.requests, 'get', Mock(return_value=Mock(
        status_code=status, text=xml_fixture('acknowledgement_no_data.xml'))))
    if status == 200:
        assert prices.fetch_day_ahead_prices('DE-LU', START, END) == []
    else:
        with pytest.raises(RuntimeError, match='HTTP 401'):
            prices.fetch_day_ahead_prices('DE-LU', START, END)


def test_invalid_token(monkeypatch):
    # Synthetic error response: a real invalid-token response was not provided.
    xml = '<Acknowledgement_MarketDocument><Reason><code>999</code><text>Invalid security token</text></Reason></Acknowledgement_MarketDocument>'
    monkeypatch.setenv('ENTSOE_API_TOKEN', 'fake-invalid-token')
    monkeypatch.setattr(prices.requests, 'get', Mock(return_value=Mock(status_code=401, text=xml)))
    with pytest.raises(RuntimeError, match='HTTP 401.*Invalid security token') as error:
        prices.fetch_day_ahead_prices('FI', START, END)
    assert 'fake-invalid-token' not in str(error.value)
    with pytest.raises(RuntimeError, match='Invalid security token'):
        prices.parse_day_ahead_prices(xml, 'FI')


def test_missing_token_prevents_request(monkeypatch):
    get = Mock()
    monkeypatch.setattr(prices.requests, 'get', get)
    with pytest.raises(RuntimeError, match='ENTSOE_API_TOKEN'):
        prices.fetch_day_ahead_prices('FI', START, END)
    get.assert_not_called()


def test_network_exception_does_not_expose_token(monkeypatch):
    monkeypatch.setenv('ENTSOE_API_TOKEN', 'fake-private-token')
    monkeypatch.setattr(prices.requests, 'get', Mock(side_effect=requests.Timeout('url?securityToken=fake-private-token')))
    with pytest.raises(RuntimeError, match='Timeout') as error:
        prices.fetch_day_ahead_prices('FI', START, END)
    assert 'fake-private-token' not in str(error.value)
    assert error.value.__suppress_context__


def test_negative_price_is_preserved(xml_fixture):
    # Synthetic mutation: the supplied FI fixture has no negative prices.
    root = ET.fromstring(xml_fixture('fi_pt15m_with_negative_prices.xml'))
    root.find('.//{*}price.amount').text = '-12.34'
    rows = prices.parse_day_ahead_prices(ET.tostring(root, encoding='unicode'), 'FI')
    assert len(rows) == 96
    assert rows[0][4] == Decimal('-12.34')
