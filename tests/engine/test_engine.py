from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from services.engine import recommend
from services.engine.contracts import EngineRequest


UTC = timezone.utc
START = datetime(2026, 11, 26, 10, tzinfo=UTC)


def _hours(prices, *, temperatures=None, estimated=None):
    temperatures = temperatures or [10.0] * len(prices)
    estimated = estimated or [False] * len(prices)
    return [
        {
            "timestamp": START + timedelta(hours=index),
            "price_eur_per_mwh": price,
            "temperature_c": temperatures[index],
            "price_is_estimated": estimated[index],
        }
        for index, price in enumerate(prices)
    ]


def _datacenter(datacenter_id, prices, *, max_power_kw=500, **kwargs):
    return {
        "datacenter_id": datacenter_id,
        "zone": kwargs.pop("zone", datacenter_id[:2]),
        "base_pue": kwargs.pop("base_pue", 1.2),
        "max_power_kw": max_power_kw,
        "hours": _hours(prices, **kwargs),
    }


def _request(datacenters, *, duration_minutes=60, deadline_hours=3, **kwargs):
    earliest_start = kwargs.pop("earliest_start", START)
    return EngineRequest(
        job_id="job-1",
        duration_minutes=duration_minutes,
        required_power_kw=100,
        earliest_start=earliest_start,
        deadline=START + timedelta(hours=deadline_hours),
        allowed_zones=[datacenter["zone"] for datacenter in datacenters],
        datacenters=datacenters,
        preferred_datacenter_id=kwargs.pop(
            "preferred_datacenter_id", datacenters[0]["datacenter_id"]
        ),
        baseline_start=kwargs.pop("baseline_start", START),
        **kwargs,
    )


def test_recommends_cheapest_window_and_prices_for_partial_last_hour():
    request = _request(
        [
            _datacenter("FI-1", [50, 20, 80]),
            _datacenter("DE-1", [40, 30, 70]),
        ],
        duration_minutes=90,
        deadline_hours=2,
    )

    response = recommend(request)

    recommendation = response.recommendations[0]
    assert recommendation.target_datacenter == "DE-1"
    assert recommendation.recommended_end == START + timedelta(minutes=90)
    assert [hour.minutes for hour in recommendation.hourly_costs] == [60, 30]
    assert recommendation.estimated_cost_eur == pytest.approx(6.6)
    assert recommendation.baseline_cost_eur == pytest.approx(7.2)
    assert recommendation.estimated_savings_eur == pytest.approx(0.6)
    assert recommendation.estimated_savings_percent == pytest.approx(8.3333333)
    assert recommendation.estimated_energy_kwh == pytest.approx(180.0)
    assert recommendation.is_fallback is False


def test_skips_datacenter_that_cannot_supply_required_power():
    request = _request(
        [
            _datacenter("FI-1", [1, 1], max_power_kw=50),
            _datacenter("DE-1", [20, 20]),
        ],
        deadline_hours=1,
        preferred_datacenter_id="DE-1",
    )

    response = recommend(request)

    assert response.recommendations[0].target_datacenter == "DE-1"


def test_dynamic_pue_is_used_for_warm_hours():
    request = _request(
        [_datacenter("FI-1", [100], temperatures=[20])],
        deadline_hours=1,
    )

    response = recommend(request)

    # PUE = 1.2 + 0.008 * (20 - 10) = 1.28.
    assert response.recommendations[0].hourly_costs[0].pue == pytest.approx(1.28)
    assert response.recommendations[0].estimated_cost_eur == pytest.approx(12.8)
    assert response.recommendations[0].estimated_energy_kwh == pytest.approx(128.0)


def test_mid_hour_earliest_start_moves_candidate_to_next_full_hour():
    mid_hour = START + timedelta(minutes=30)
    request = _request(
        [_datacenter("FI-1", [100, 10, 100])],
        deadline_hours=2,
        earliest_start=mid_hour,
        baseline_start=mid_hour,
    )

    response = recommend(request)

    recommendation = response.recommendations[0]
    assert recommendation.recommended_start == START + timedelta(hours=1)
    assert recommendation.recommended_end == START + timedelta(hours=2)
    assert recommendation.baseline_cost_eur == pytest.approx(6.6)
    assert recommendation.estimated_cost_eur == pytest.approx(1.2)


def test_negative_price_and_zero_baseline_keep_percent_null():
    request = _request(
        [_datacenter("FI-1", [-10, 10])],
        deadline_hours=2,
    )

    response = recommend(request)

    recommendation = response.recommendations[0]
    assert recommendation.estimated_cost_eur == pytest.approx(-1.2)
    assert recommendation.baseline_cost_eur == pytest.approx(-1.2)
    assert recommendation.estimated_savings_eur == pytest.approx(0.0)
    assert recommendation.estimated_savings_percent == pytest.approx(0.0)

    zero_request = _request([_datacenter("FI-1", [0])], deadline_hours=1)
    zero_response = recommend(zero_request)
    assert zero_response.recommendations[0].estimated_savings_percent is None


def test_estimated_window_is_returned_without_confirmed_window():
    request = _request(
        [
            _datacenter(
                "FI-1",
                [20, 10],
                estimated=[True, True],
            )
        ],
        deadline_hours=2,
    )

    response = recommend(request)

    assert response.reason == "no_confirmed_window"
    assert len(response.recommendations) == 1
    assert response.recommendations[0].is_fallback is True


def test_baseline_estimated_excludes_confirmed_recommendation():
    request = _request(
        [
            _datacenter(
                "FI-1",
                [10, 20],
                estimated=[False, True],
            )
        ],
        deadline_hours=2,
        baseline_start=START + timedelta(hours=1),
    )

    response = recommend(request)

    assert response.reason == "baseline_estimated"
    assert len(response.recommendations) == 1
    assert response.recommendations[0].is_fallback is True
    assert response.recommendations[0].baseline_has_estimated_price is True
    assert response.recommendations[0].recommended_start == START
    assert response.recommendations[0].estimated_cost_eur == pytest.approx(1.2)


def test_no_candidate_window_returns_data_unavailable():
    request = _request(
        [_datacenter("FI-1", [10])],
        earliest_start=START + timedelta(minutes=30),
        baseline_start=START + timedelta(minutes=30),
        deadline_hours=1,
    )

    response = recommend(request)

    assert response.reason == "data_unavailable"
    assert response.recommendations == []


def test_missing_temperature_uses_base_pue(caplog):
    request = _request(
        [_datacenter("FI-1", [100], temperatures=[None])],
        deadline_hours=1,
    )

    response = recommend(request)

    assert response.recommendations[0].hourly_costs[0].pue == pytest.approx(1.2)
    assert "temperature forecast is unavailable" in caplog.text


def test_returns_confirmed_and_fallback_recommendations_when_both_are_useful():
    request = _request(
        [_datacenter("FI-1", [10, 1], estimated=[False, True])],
        deadline_hours=2,
    )

    response = recommend(request)

    assert len(response.recommendations) == 2
    assert response.recommendations[0].is_fallback is False
    assert response.recommendations[1].is_fallback is True
    assert response.recommendations[0].recommended_start == START
    assert response.recommendations[1].recommended_start == START + timedelta(hours=1)


def test_missing_baseline_data_returns_data_unavailable():
    request = _request([_datacenter("FI-1", [])], deadline_hours=1)

    response = recommend(request)

    assert response.reason == "data_unavailable"
    assert response.recommendations == []


def test_hour_series_must_be_continuous():
    with pytest.raises(ValidationError, match="continuous hourly grid"):
        _request(
            [
                {
                    **_datacenter("FI-1", [10, 20]),
                    "hours": [
                        _hours([10])[0],
                        {
                            **_hours([20])[0],
                            "timestamp": START + timedelta(hours=2),
                        },
                    ],
                }
            ],
            deadline_hours=1,
        )
