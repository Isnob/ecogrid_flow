"""HTTP contract for POST /api/v1/recommendations (Pydantic v2).

These models describe the wire format. Database lookups, calculation and
translation of Pydantic ValidationError into ErrorResponse belong to the API
handler, which is not implemented yet.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isclose
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)


def _iso_datetime_input(value: object) -> object:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("date and time must be an ISO 8601 string with UTC offset")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("date and time must be an ISO 8601 string") from exc
    return value


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("date and time must be in UTC (Z or +00:00)")
    return value.astimezone(timezone.utc)


def _serialize_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _whole_hour(value: datetime) -> bool:
    return value.minute == value.second == value.microsecond == 0


UtcDateTime = Annotated[
    datetime,
    BeforeValidator(_iso_datetime_input),
    AfterValidator(_utc_datetime),
    PlainSerializer(_serialize_utc, return_type=str, when_used="json"),
]
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RecommendationRequest(ApiModel):
    """Client task and baseline; the API resolves the default datacenter."""

    job_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    duration_minutes: int = Field(gt=0, strict=True)
    required_power_kw: float = Field(gt=0)
    deadline: UtcDateTime
    earliest_start: UtcDateTime = Field(default_factory=lambda: datetime.now(timezone.utc))
    allowed_zones: list[NonEmptyString] = Field(min_length=1)
    preferred_datacenter_id: NonEmptyString | None = None
    baseline_start: UtcDateTime | None = None

    @field_validator("allowed_zones")
    @classmethod
    def unique_zones(cls, zones: list[str]) -> list[str]:
        if len(zones) != len(set(zones)):
            raise ValueError("allowed_zones must not contain duplicates")
        return zones

    @model_validator(mode="after")
    def validate_window(self) -> RecommendationRequest:
        latest_start = self.deadline - timedelta(minutes=self.duration_minutes)
        if self.earliest_start > latest_start:
            raise ValueError("deadline must allow the full duration after earliest_start")
        if self.baseline_start is None:
            self.baseline_start = self.earliest_start
        if not self.earliest_start <= self.baseline_start <= latest_start:
            raise ValueError("baseline_start must be between earliest_start and deadline - duration_minutes")
        return self


class HourlyCost(ApiModel):
    """One point of the selected window for the frontend cost chart."""

    timestamp: UtcDateTime
    minutes: int = Field(gt=0, le=60, strict=True)
    price_eur_per_mwh: float
    temperature_c: float | None
    pue: float = Field(ge=1)
    cost_eur: float
    price_is_estimated: StrictBool

    @field_validator("timestamp")
    @classmethod
    def validate_hour_start(cls, value: datetime) -> datetime:
        if not _whole_hour(value):
            raise ValueError("timestamp must be the start of a UTC hour")
        return value


class Recommendation(ApiModel):
    recommendation_id: int = Field(gt=0, strict=True)
    target_datacenter: NonEmptyString
    recommended_start: UtcDateTime
    recommended_end: UtcDateTime
    estimated_cost_eur: float
    baseline_cost_eur: float
    estimated_savings_eur: float
    estimated_savings_percent: float | None
    is_fallback: StrictBool
    hourly_costs: list[HourlyCost] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_interval(self) -> Recommendation:
        if self.recommended_end <= self.recommended_start:
            raise ValueError("recommended_end must be after recommended_start")
        if not _whole_hour(self.recommended_start):
            raise ValueError("recommended_start must be the start of a UTC hour")
        if self.recommended_end.second or self.recommended_end.microsecond:
            raise ValueError("recommended_end must have minute precision")
        if (self.baseline_cost_eur == 0) != (self.estimated_savings_percent is None):
            raise ValueError("estimated_savings_percent must be null exactly when baseline_cost_eur is zero")
        if not isclose(
            self.estimated_savings_eur,
            self.baseline_cost_eur - self.estimated_cost_eur,
            rel_tol=1e-8,
            abs_tol=1e-4,
        ):
            raise ValueError("estimated_savings_eur must equal baseline_cost_eur - estimated_cost_eur")
        if self.baseline_cost_eur != 0 and not isclose(
            self.estimated_savings_percent,
            self.estimated_savings_eur / self.baseline_cost_eur * 100,
            rel_tol=1e-8,
            abs_tol=1e-4,
        ):
            raise ValueError("estimated_savings_percent does not match the cost ratio")
        for index, point in enumerate(self.hourly_costs):
            if point.timestamp != self.recommended_start + timedelta(hours=index):
                raise ValueError("hourly_costs must contain consecutive UTC hours in order")
            billed_until = min(self.recommended_end, point.timestamp + timedelta(hours=1))
            expected_minutes = int((billed_until - point.timestamp).total_seconds() / 60)
            if point.minutes != expected_minutes:
                raise ValueError("hourly_costs.minutes must match the occupied part of its hour")
        if self.recommended_end > self.hourly_costs[-1].timestamp + timedelta(hours=1):
            raise ValueError("hourly_costs must cover the end of the selected window")
        if self.recommended_end <= self.hourly_costs[-1].timestamp:
            raise ValueError("hourly_costs must not extend beyond the selected window")
        if not isclose(
            self.estimated_cost_eur,
            sum(point.cost_eur for point in self.hourly_costs),
            rel_tol=1e-8,
            abs_tol=1e-4 * len(self.hourly_costs),
        ):
            raise ValueError("estimated_cost_eur must equal the sum of hourly_costs")
        if not self.is_fallback and any(point.price_is_estimated for point in self.hourly_costs):
            raise ValueError("a confirmed recommendation cannot use estimated hourly prices")
        return self


NoPrimaryReason = Literal["no_confirmed_window", "baseline_estimated"]


class RecommendationResponse(ApiModel):
    job_id: NonEmptyString
    recommendations: list[Recommendation] = Field(min_length=1, max_length=2)
    reason: NoPrimaryReason | None = None

    @model_validator(mode="after")
    def validate_recommendation_set(self) -> RecommendationResponse:
        flags = [item.is_fallback for item in self.recommendations]
        if len(flags) != len(set(flags)):
            raise ValueError("at most one confirmed and one estimated recommendation are allowed")
        has_primary = False in flags
        if has_primary and self.reason is not None:
            raise ValueError("reason must be null when a confirmed recommendation exists")
        if not has_primary and self.reason is None:
            raise ValueError("reason is required when no confirmed recommendation exists")
        if self.reason == "no_confirmed_window" and not any(
            point.price_is_estimated
            for recommendation in self.recommendations
            for point in recommendation.hourly_costs
        ):
            raise ValueError("no_confirmed_window requires an estimated price in the selected window")
        return self


ErrorCode = Literal["invalid_request", "unauthorized", "data_unavailable", "internal_error"]


class ErrorDetail(ApiModel):
    field: NonEmptyString
    message: NonEmptyString


class ErrorInfo(ApiModel):
    code: ErrorCode
    message: NonEmptyString
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(ApiModel):
    error: ErrorInfo
