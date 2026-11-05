from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import requests

from collectors import open_meteo, open_meteo_historical


@pytest.fixture(params=['forecast', 'historical'])
def collector(request):
    if request.param == 'forecast':
        return ('forecast', open_meteo, open_meteo.fetch_weather_forecast,
                {'forecast_days': 2}, open_meteo.OPEN_METEO_BASE_URL, 10)
    return ('historical', open_meteo_historical, open_meteo_historical.fetch_historical_weather,
            {'start_date': '2023-10-01', 'end_date': '2023-10-02'},
            open_meteo_historical.OPEN_METEO_ARCHIVE_URL, 30)


def test_real_response_mapping_and_request(monkeypatch, weather_fixture, collector):
    name, module, fetch, options, url, timeout = collector
    data = weather_fixture(name)
    response = Mock()
    response.json.return_value = data
    get = Mock(return_value=response)
    monkeypatch.setattr(module.requests, 'get', get)
    rows = fetch(60.1695, 24.9354, **options)
    assert len(rows) == 48
    fields = ['temperature_2m', 'relative_humidity_2m', 'cloud_cover', 'wind_speed_10m', 'shortwave_radiation']
    for i, row in enumerate(rows):
        assert row == (datetime.fromisoformat(data['hourly']['time'][i]).replace(tzinfo=timezone.utc),
                       *(data['hourly'][field][i] for field in fields))
    assert all(b[0] - a[0] == timedelta(hours=1) for a, b in zip(rows, rows[1:]))
    get.assert_called_once_with(url, params={
        'latitude': 60.1695, 'longitude': 24.9354,
        'hourly': ','.join(fields), 'timezone': 'GMT', **options,
    }, timeout=timeout)
    response.raise_for_status.assert_called_once_with()


def test_null_value_does_not_shift_columns(monkeypatch, weather_fixture, collector):
    name, module, fetch, options, _, _ = collector
    data = weather_fixture(name)
    data['hourly']['temperature_2m'][1] = None
    response = Mock()
    response.json.return_value = data
    monkeypatch.setattr(module.requests, 'get', Mock(return_value=response))
    rows = fetch(60.1695, 24.9354, **options)
    assert len(rows) == 48
    assert rows[1][1] is None
    assert rows[1][2] == data['hourly']['relative_humidity_2m'][1]
    assert rows[2][1] == data['hourly']['temperature_2m'][2]


@pytest.mark.parametrize('payload', [{}, {'hourly': {}}])
def test_empty_response(monkeypatch, collector, payload):
    _, module, fetch, options, _, _ = collector
    response = Mock()
    response.json.return_value = payload
    monkeypatch.setattr(module.requests, 'get', Mock(return_value=response))
    assert fetch(60.1695, 24.9354, **options) == []


def test_http_error_before_json_parsing(monkeypatch, collector):
    _, module, fetch, options, _, _ = collector
    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError('503 unavailable')
    monkeypatch.setattr(module.requests, 'get', Mock(return_value=response))
    with pytest.raises(requests.HTTPError):
        fetch(60.1695, 24.9354, **options)
    response.json.assert_not_called()


def test_timeout(monkeypatch, collector):
    _, module, fetch, options, _, _ = collector
    monkeypatch.setattr(module.requests, 'get', Mock(side_effect=requests.Timeout('timeout')))
    with pytest.raises(requests.Timeout):
        fetch(60.1695, 24.9354, **options)
