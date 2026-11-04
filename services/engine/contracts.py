"""Public input/output contract for the calculation engine.

The engine is intentionally independent from the database and HTTP layer.
The API prepares hourly rows and calls :func:`recommend`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EngineModel(BaseModel):
    """Base model with a strict JSON contract."""

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "timestamp",
        "earliest_start",
        "deadline",
        "baseline_start",
        "recommended_start",
        "recommended_end",
        mode="after",
        check_fields=False,
    )
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        """Reject naive/local timestamps: K3 uses UTC ISO 8601 values."""

        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("timestamp must include UTC timezone (ISO 8601 with Z)")
        return value.astimezone(timezone.utc)


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

    @field_validator("timestamp")
    @classmethod
    def require_hour_boundary(cls, value: datetime) -> datetime:
        if value.minute or value.second or value.microsecond:
            raise ValueError("hour timestamp must be aligned to the start of an hour")
        return value


class DatacenterInput(EngineModel):
    """Datacenter parameters and the hourly series prepared by the API."""

    datacenter_id: str
    zone: str
    base_pue: float = Field(ge=1.0)
    max_power_kw: float = Field(gt=0.0)
    hours: list[HourInput] = Field(
        default_factory=list,
        description="Chronological hourly rows; can be empty when data is unavailable.",
    )

    @model_validator(mode="after")
    def validate_hour_series(self) -> "DatacenterInput":
        timestamps = [hour.timestamp for hour in self.hours]
        if len(timestamps) != len(set(timestamps)):
            raise ValueError("hours must not contain duplicate timestamps")
        if timestamps != sorted(timestamps):
            raise ValueError("hours must be sorted chronologically")
        return self


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

    @model_validator(mode="after")
    def validate_request_window(self) -> "EngineRequest":
        latest_start = self.deadline - timedelta(minutes=self.duration_minutes)
        if self.deadline < self.earliest_start + timedelta(minutes=self.duration_minutes):
            raise ValueError("deadline must leave enough time for the task")
        if not self.earliest_start <= self.baseline_start <= latest_start:
            raise ValueError("baseline_start must be inside the feasible task interval")
        if self.preferred_datacenter_id not in {
            datacenter.datacenter_id for datacenter in self.datacenters
        }:
            raise ValueError("preferred_datacenter_id must refer to a supplied datacenter")
        if any(datacenter.zone not in self.allowed_zones for datacenter in self.datacenters):
            raise ValueError("every datacenter zone must be included in allowed_zones")
        return self


class HourCost(EngineModel):
    """Cost breakdown for one hour of the selected recommendation."""

    timestamp: datetime
    minutes: int = Field(gt=0, le=60, description="Billed minutes in this hour.")
    price_eur_per_mwh: float
    temperature_c: Optional[float]
    pue: float = Field(ge=1.0)
    cost_eur: float
    price_is_estimated: bool


class Recommendation(EngineModel):
    """One confirmed or estimated execution option."""

    recommendation_id: Optional[str] = Field(
        default=None,
        description="Assigned by API/DB after the engine result is persisted.",
    )
    target_datacenter: str
    recommended_start: datetime
    recommended_end: datetime
    estimated_cost_eur: float
    baseline_cost_eur: float
    estimated_savings_eur: float
    estimated_savings_percent: Optional[float] = Field(
        default=None,
        description="Null when baseline_cost_eur is zero, because division is undefined.",
    )
    is_fallback: bool
    hourly_costs: list[HourCost] = Field(min_length=1)
    baseline_has_estimated_price: bool = Field(
        default=False,
        description="True when baseline_cost_eur used at least one estimated price.",
    )

    @model_validator(mode="after")
    def validate_fallback_flag(self) -> "Recommendation":
        has_estimated_price = self.baseline_has_estimated_price or any(
            hour.price_is_estimated for hour in self.hourly_costs
        )
        if self.is_fallback != has_estimated_price:
            raise ValueError(
                "is_fallback must be true if the recommendation or baseline uses "
                "an estimated price"
            )
        return self


class EngineResponse(EngineModel):
    """Result returned by the engine and passed through by the API."""

    job_id: str
    recommendations: list[Recommendation] = Field(max_length=2)
    reason: Optional[
        Literal["no_confirmed_window", "baseline_estimated", "data_unavailable"]
    ] = None

    @model_validator(mode="after")
    def validate_empty_result(self) -> "EngineResponse":
        if not self.recommendations and self.reason != "data_unavailable":
            raise ValueError(
                "an empty result is allowed only with reason=data_unavailable"
            )
        if self.reason == "data_unavailable" and self.recommendations:
            raise ValueError("data_unavailable response must not contain recommendations")
        return self


def recommend(request: EngineRequest) -> EngineResponse:
    """Return the cheapest feasible recommendation(s) for the request."""

    ...
