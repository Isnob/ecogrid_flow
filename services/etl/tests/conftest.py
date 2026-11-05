"""Offline fixtures shared by ETL tests."""
import json
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Unexpected real HTTP request: use a saved fixture')
    monkeypatch.setattr(requests.sessions.Session, 'request', forbidden)
    monkeypatch.delenv('ENTSOE_API_TOKEN', raising=False)


@pytest.fixture
def xml_fixture():
    return lambda name: (FIXTURES / 'entsoe' / name).read_text(encoding='utf-8')


@pytest.fixture
def weather_fixture():
    return lambda name: json.loads((FIXTURES / f'open_meteo_{name}.json').read_text(encoding='utf-8'))
