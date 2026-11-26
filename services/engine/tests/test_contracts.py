"""Unit tests for K3 (services.engine.contracts) and K4 (services.api.schemas) contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from services.api.schemas import (
    ErrorResponse,
    RecommendationRequest,
    RecommendationResponse,
)
from services.engine.contracts import (
    DatacenterInput,
    EngineRequest,
    EngineResponse,
    HourCost,
    HourInput,
    Recommendation,
)


def _sample_hour_inputs() -> list[HourInput]:
    return [
        HourInput(
            timestamp=datetime(2026, 11, 3, 10, tzinfo=UTC),
            price_eur_per_mwh=42.5,
            temperature_c=4.0,
            price_is_estimated=False,
        ),
        HourInput(
            timestamp=datetime(2026, 11, 3, 11, tzinfo=UTC),
            price_eur_per_mwh=39.0,
            temperature_c=4.5,
            price_is_estimated=False,
        ),
    ]


def _sample_engine_recommendation(
    *,
    recommendation_id: int | None = None,
    is_fallback: bool = False,
    baseline_has_estimated_price: bool = False,
    price_is_estimated: bool = False,
    baseline_cost_eur: float = 9.3725,
    estimated_cost_eur: float = 8.51,
    estimated_savings_eur: float = 0.8625,
    estimated_savings_percent: float | None = 9.20245,
) -> Recommendation:
    return Recommendation(
        recommendation_id=recommendation_id,
        target_datacenter="FI-HELSINKI-01",
        recommended_start=datetime(2026, 11, 3, 11, tzinfo=UTC),
        recommended_end=datetime(2026, 11, 3, 13, tzinfo=UTC),
        estimated_energy_kwh=230.0,
        estimated_cost_eur=estimated_cost_eur,
        baseline_cost_eur=baseline_cost_eur,
        estimated_savings_eur=estimated_savings_eur,
        estimated_savings_percent=estimated_savings_percent,
        is_fallback=is_fallback,
        baseline_has_estimated_price=baseline_has_estimated_price,
        hourly_costs=[
            HourCost(
                timestamp=datetime(2026, 11, 3, 11, tzinfo=UTC),
                minutes=60,
                price_eur_per_mwh=39.0,
                temperature_c=4.5,
                pue=1.15,
                cost_eur=4.485,
                price_is_estimated=price_is_estimated,
            ),
            HourCost(
                timestamp=datetime(2026, 11, 3, 12, tzinfo=UTC),
                minutes=60,
                price_eur_per_mwh=35.0,
                temperature_c=5.0,
                pue=1.15,
                cost_eur=4.025,
                price_is_estimated=price_is_estimated,
            ),
        ],
    )


def test_engine_request_accepts_continuous_utc_series() -> None:
    req = EngineRequest(
        job_id="job-123",
        duration_minutes=120,
        required_power_kw=100.0,
        earliest_start=datetime(2026, 11, 3, 10, tzinfo=UTC),
        deadline=datetime(2026, 11, 4, 10, tzinfo=UTC),
        allowed_zones=["FI"],
        preferred_datacenter_id="FI-HELSINKI-01",
        baseline_start=datetime(2026, 11, 3, 10, tzinfo=UTC),
        datacenters=[
            DatacenterInput(
                datacenter_id="FI-HELSINKI-01",
                zone="FI",
                base_pue=1.15,
                max_power_kw=500.0,
                hours=_sample_hour_inputs(),
            ),
        ],
    )
    assert req.datacenters[0].datacenter_id == "FI-HELSINKI-01"


def test_datacenter_input_rejects_hourly_gaps() -> None:
    with pytest.raises(ValidationError, match="continuous hourly grid"):
        DatacenterInput(
            datacenter_id="FI-HELSINKI-01",
            zone="FI",
            base_pue=1.15,
            max_power_kw=500.0,
            hours=[
                HourInput(
                    timestamp=datetime(2026, 11, 3, 10, tzinfo=UTC),
                    price_eur_per_mwh=40.0,
                ),
                HourInput(
                    timestamp=datetime(2026, 11, 3, 12, tzinfo=UTC),
                    price_eur_per_mwh=42.0,
                ),
            ],
        )


def test_engine_recommendation_supports_none_or_positive_int_id_and_energy_kwh() -> None:
    rec_none = _sample_engine_recommendation(recommendation_id=None)
    assert rec_none.recommendation_id is None
    assert rec_none.estimated_energy_kwh == 230.0

    rec_int = _sample_engine_recommendation(recommendation_id=101)
    assert rec_int.recommendation_id == 101

    with pytest.raises(ValidationError):
        _sample_engine_recommendation(recommendation_id="rec-101")  # type: ignore[arg-type]


def test_engine_recommendation_rejects_nan_and_mismatched_totals() -> None:
    with pytest.raises(ValidationError):
        HourInput(
            timestamp=datetime(2026, 11, 3, 10, tzinfo=UTC),
            price_eur_per_mwh=float("nan"),
        )

    with pytest.raises(ValidationError, match="estimated_savings_eur"):
        _sample_engine_recommendation(estimated_savings_eur=99.0)

    with pytest.raises(ValidationError, match="sum of hourly_costs"):
        _sample_engine_recommendation(
            estimated_cost_eur=10.0,
            baseline_cost_eur=12.0,
            estimated_savings_eur=2.0,
            estimated_savings_percent=16.66667,
        )


def test_engine_response_modes_and_constraints() -> None:
    confirmed = _sample_engine_recommendation(is_fallback=False)
    estimated = _sample_engine_recommendation(
        is_fallback=True,
        price_is_estimated=True,
    )
    ok_resp = EngineResponse(
        job_id="job-123",
        recommendations=[confirmed, estimated],
        reason=None,
    )
    assert len(ok_resp.recommendations) == 2

    with pytest.raises(ValidationError, match="at most one confirmed and one estimated"):
        EngineResponse(
            job_id="job-123",
            recommendations=[confirmed, confirmed],
            reason=None,
        )

    with pytest.raises(ValidationError, match="no_confirmed_window requires an estimated price"):
        EngineResponse(
            job_id="job-123",
            recommendations=[
                _sample_engine_recommendation(
                    is_fallback=True,
                    baseline_has_estimated_price=True,
                    price_is_estimated=False,
                ),
            ],
            reason="no_confirmed_window",
        )

    baseline_only = EngineResponse(
        job_id="job-123",
        recommendations=[
            _sample_engine_recommendation(
                is_fallback=True,
                baseline_has_estimated_price=True,
                price_is_estimated=False,
            ),
        ],
        reason="baseline_estimated",
    )
    assert baseline_only.reason == "baseline_estimated"

    unavailable = EngineResponse(
        job_id="job-123",
        recommendations=[],
        reason="data_unavailable",
    )
    assert unavailable.reason == "data_unavailable"


def test_api_schemas_validate_request_response_and_error() -> None:
    req = RecommendationRequest.model_validate(
        {
            "job_id": "job-123",
            "duration_minutes": 120,
            "required_power_kw": 100,
            "earliest_start": "2026-11-03T10:00:00Z",
            "deadline": "2026-11-04T10:00:00Z",
            "allowed_zones": ["FI"],
            "preferred_datacenter_id": "FI-HELSINKI-01",
            "baseline_start": "2026-11-03T10:00:00Z",
        },
    )
    assert req.job_id == "job-123"

    with pytest.raises(ValidationError):
        RecommendationRequest.model_validate(
            {
                "job_id": "job-123",
                "task_name": "Extra field rejected",
                "duration_minutes": 120,
                "required_power_kw": 100,
                "earliest_start": "2026-11-03T10:00:00Z",
                "deadline": "2026-11-04T10:00:00Z",
                "allowed_zones": ["FI"],
            },
        )

    valid_response_payload = {
        "job_id": "job-123",
        "recommendations": [
            {
                "recommendation_id": 101,
                "target_datacenter": "FI-HELSINKI-01",
                "recommended_start": "2026-11-03T11:00:00Z",
                "recommended_end": "2026-11-03T13:00:00Z",
                "estimated_cost_eur": 8.51,
                "baseline_cost_eur": 9.3725,
                "estimated_savings_eur": 0.8625,
                "estimated_savings_percent": 9.20245,
                "is_fallback": False,
                "hourly_costs": [
                    {
                        "timestamp": "2026-11-03T11:00:00Z",
                        "minutes": 60,
                        "price_eur_per_mwh": 39,
                        "temperature_c": 4.5,
                        "pue": 1.15,
                        "cost_eur": 4.485,
                        "price_is_estimated": False,
                    },
                    {
                        "timestamp": "2026-11-03T12:00:00Z",
                        "minutes": 60,
                        "price_eur_per_mwh": 35,
                        "temperature_c": 5.0,
                        "pue": 1.15,
                        "cost_eur": 4.025,
                        "price_is_estimated": False,
                    },
                ],
            },
        ],
        "reason": None,
        "search_timelines": [
            {
                "target_datacenter": "FI-HELSINKI-01",
                "hours": [
                    {
                        "timestamp": "2026-11-03T11:00:00Z",
                        "price_eur_per_mwh": 39,
                        "temperature_c": 4.5,
                        "price_is_estimated": False,
                    },
                    {
                        "timestamp": "2026-11-03T12:00:00Z",
                        "price_eur_per_mwh": 35,
                        "temperature_c": 5.0,
                        "price_is_estimated": False,
                    },
                ],
            },
        ],
    }

    resp = RecommendationResponse.model_validate(valid_response_payload)
    assert resp.recommendations[0].recommendation_id == 101
    assert resp.search_timelines[0].target_datacenter == "FI-HELSINKI-01"
    assert len(resp.search_timelines[0].hours) == 2

    with pytest.raises(ValidationError):
        RecommendationResponse.model_validate(
            {k: v for k, v in valid_response_payload.items() if k != "search_timelines"}
        )

    with pytest.raises(ValidationError):
        RecommendationResponse.model_validate(
            {
                **valid_response_payload,
                "search_timelines": [
                    {
                        "target_datacenter": "FI-HELSINKI-01",
                        "hours": [
                            {
                                "timestamp": "2026-11-03T11:00:00Z",
                                "price_eur_per_mwh": 39,
                                "temperature_c": 4.5,
                                "pue": 1.15,
                                "price_is_estimated": False,
                            },
                            {
                                "timestamp": "2026-11-03T12:00:00Z",
                                "price_eur_per_mwh": 35,
                                "temperature_c": 5.0,
                                "price_is_estimated": False,
                            },
                        ],
                    },
                ],
            }
        )

    with pytest.raises(ValidationError):
        RecommendationResponse.model_validate(
            {
                **valid_response_payload,
                "search_timelines": [
                    {
                        "target_datacenter": "FI-HELSINKI-01",
                        "hours": [
                            {
                                "timestamp": "2026-11-03T11:00:00Z",
                                "price_eur_per_mwh": 39,
                                "temperature_c": 4.5,
                                "price_is_estimated": False,
                            },
                        ],
                    },
                ],
            }
        )

    err = ErrorResponse.model_validate(
        {
            "error": {
                "code": "data_unavailable",
                "message": "Not enough price data to calculate a recommendation",
                "details": [],
            },
        },
    )
    assert err.error.code == "data_unavailable"
