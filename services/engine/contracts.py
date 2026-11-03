"""Public input/output contract for the calculation engine.

The engine is intentionally independent from the database and HTTP layer.
The API prepares hourly rows and calls :func:`recommend`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class EngineModel(BaseModel):
    """Base model with a strict JSON contract."""

    model_config = ConfigDict(extra="forbid")


class HourInput(EngineModel):
    """All data needed to price one hour for one datacenter."""

    timestamp: datetime = Field(description="Start of the hour, UTC.")
    price_eur_per_mwh: float = Field(description="Electricity price for the hour.")
    temperature_c: Optional[float] = Field(
        default=None,
        description="Outdoor temperature in Celsius from the weather forecast.",
    )
    price_is_estimated: bool = Field(
        default=False,
        description="True when the price came from the fallback estimator.",
    )


class DatacenterInput(EngineModel):
    """Datacenter parameters and the hourly series prepared by the API."""

    datacenter_id: str
    zone: str
    base_pue: float = Field(ge=1.0)
    max_power_kw: float = Field(gt=0.0)
    hours: list[HourInput] = Field(min_length=1)


class EngineRequest(EngineModel):
    """Request passed from the API to the calculation engine."""

    job_id: str
    duration_minutes: int = Field(gt=0)
    required_power_kw: float = Field(gt=0.0)
    earliest_start: datetime
    deadline: datetime
    allowed_zones: list[str] = Field(min_length=1)
    datacenters: list[DatacenterInput] = Field(min_length=1)
    preferred_datacenter_id: str
    baseline_start: datetime


class HourCost(EngineModel):
    """Cost breakdown for one hour of the selected recommendation."""

    timestamp: datetime
    price_eur_per_mwh: float
    temperature_c: Optional[float]
    pue: float = Field(ge=1.0)
    cost_eur: float
    price_is_estimated: bool


class Recommendation(EngineModel):
    """One confirmed or estimated execution option."""

    recommendation_id: str
    target_datacenter: str
    recommended_start: datetime
    recommended_end: datetime
    estimated_cost_eur: float
    baseline_cost_eur: float
    estimated_savings_eur: float
    estimated_savings_percent: float
    is_fallback: bool
    hourly_costs: list[HourCost] = Field(min_length=1)


class EngineResponse(EngineModel):
    """Result returned by the engine and passed through by the API."""

    job_id: str
    recommendations: list[Recommendation] = Field(max_length=2)
    reason: Optional[Literal["no_confirmed_window", "baseline_estimated"]] = None


def recommend(request: EngineRequest) -> EngineResponse:
    """Return the cheapest feasible recommendation(s) for the request."""

    ...
