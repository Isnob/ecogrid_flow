"""Pure calculation engine for the K3 recommendation contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from .contracts import (
    DatacenterInput,
    EngineRequest,
    EngineResponse,
    HourCost,
    HourInput,
    Recommendation,
)


PUE_FREE_COOLING_LIMIT_C = 10.0
PUE_WARMING_SLOPE = 0.008
EUR_PER_MWH_TO_EUR_PER_KWH = 1 / 1000
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Window:
    datacenter: DatacenterInput
    start: datetime
    hours: tuple[HourInput, ...]
    minutes: tuple[int, ...]
    uses_estimated_price: bool
    cost_eur: float


def _pue(base_pue: float, temperature_c: float | None) -> float:
    """Return the hourly PUE from the model documented in docs/research/pue.md."""

    if temperature_c is None:
        logger.warning("temperature forecast is unavailable; using base_pue=%s", base_pue)
        return base_pue
    if temperature_c <= PUE_FREE_COOLING_LIMIT_C:
        return base_pue
    return base_pue + PUE_WARMING_SLOPE * (
        temperature_c - PUE_FREE_COOLING_LIMIT_C
    )


def _duration_hours(duration_minutes: int) -> int:
    return (duration_minutes + 59) // 60


def _first_hour(timestamp: datetime) -> datetime:
    return timestamp.replace(minute=0, second=0, microsecond=0)


def _candidate_start(timestamp: datetime) -> datetime:
    hour = _first_hour(timestamp)
    return hour if timestamp == hour else hour + timedelta(hours=1)


def _interval_rows(
    datacenter: DatacenterInput,
    start: datetime,
    duration_minutes: int,
) -> tuple[tuple[HourInput, ...], tuple[int, ...]] | None:
    """Return source hours and occupied minutes for an arbitrary start."""

    by_timestamp = {hour.timestamp: hour for hour in datacenter.hours}
    end = start + timedelta(minutes=duration_minutes)
    hour_start = _first_hour(start)
    selected: list[HourInput] = []
    minutes: list[int] = []
    while hour_start < end:
        hour_end = hour_start + timedelta(hours=1)
        overlap_start = max(start, hour_start)
        overlap_end = min(end, hour_end)
        occupied_minutes = int((overlap_end - overlap_start).total_seconds() / 60)
        hour = by_timestamp.get(hour_start)
        if hour is None or occupied_minutes <= 0:
            return None
        selected.append(hour)
        minutes.append(occupied_minutes)
        hour_start = hour_end
    return tuple(selected), tuple(minutes)


def _cost_for_interval(
    datacenter: DatacenterInput,
    hours: tuple[HourInput, ...],
    minutes: tuple[int, ...],
    required_power_kw: float,
) -> float:
    return sum(
        required_power_kw
        * _pue(datacenter.base_pue, hour.temperature_c)
        * (occupied_minutes / 60)
        * hour.price_eur_per_mwh
        * EUR_PER_MWH_TO_EUR_PER_KWH
        for hour, occupied_minutes in zip(hours, minutes)
    )


def _hour_cost_for_required_power(
    datacenter: DatacenterInput,
    hour: HourInput,
    required_power_kw: float,
) -> float:
    pue = _pue(datacenter.base_pue, hour.temperature_c)
    return (
        required_power_kw
        * pue
        * hour.price_eur_per_mwh
        * EUR_PER_MWH_TO_EUR_PER_KWH
    )


def _window_at(
    datacenter: DatacenterInput,
    start: datetime,
    duration_minutes: int,
    required_power_kw: float,
) -> _Window | None:
    rows = _interval_rows(datacenter, start, duration_minutes)
    if rows is None:
        return None
    selected_tuple, minutes = rows
    return _Window(
        datacenter=datacenter,
        start=start,
        hours=selected_tuple,
        minutes=minutes,
        uses_estimated_price=any(hour.price_is_estimated for hour in selected_tuple),
        cost_eur=_cost_for_interval(
            datacenter,
            selected_tuple,
            minutes,
            required_power_kw,
        ),
    )


def _candidate_windows(
    request: EngineRequest,
    *,
    allow_estimated: bool,
) -> list[_Window]:
    latest_start = request.deadline - timedelta(minutes=request.duration_minutes)
    candidates: list[_Window] = []
    for datacenter in request.datacenters:
        if datacenter.zone not in request.allowed_zones:
            continue
        if datacenter.max_power_kw < request.required_power_kw:
            continue

        by_timestamp = {
            hour.timestamp: index for index, hour in enumerate(datacenter.hours)
        }
        hourly_costs = [
            _hour_cost_for_required_power(
                datacenter,
                hour,
                request.required_power_kw,
            )
            for hour in datacenter.hours
        ]
        cost_prefix = [0.0]
        estimated_prefix = [0]
        for hour, cost in zip(datacenter.hours, hourly_costs):
            cost_prefix.append(cost_prefix[-1] + cost)
            estimated_prefix.append(
                estimated_prefix[-1] + int(hour.price_is_estimated)
            )

        full_hours, partial_minutes = divmod(request.duration_minutes, 60)
        hours_count = _duration_hours(request.duration_minutes)
        start = _candidate_start(request.earliest_start)
        while start <= latest_start:
            start_index = by_timestamp.get(start)
            if start_index is not None and start_index + hours_count <= len(
                datacenter.hours
            ):
                end_index = start_index + hours_count
                uses_estimated = (
                    estimated_prefix[end_index] - estimated_prefix[start_index] > 0
                )
                if allow_estimated or not uses_estimated:
                    cost = cost_prefix[start_index + full_hours] - cost_prefix[
                        start_index
                    ]
                    if partial_minutes:
                        cost += hourly_costs[end_index - 1] * partial_minutes / 60
                    candidates.append(
                        _Window(
                            datacenter=datacenter,
                            start=start,
                            hours=tuple(datacenter.hours[start_index:end_index]),
                            minutes=tuple(
                                [60] * full_hours
                                + ([partial_minutes] if partial_minutes else [])
                            ),
                            uses_estimated_price=uses_estimated,
                            cost_eur=cost,
                        )
                    )
            start += timedelta(hours=1)
    return candidates


def _best_window(windows: list[_Window]) -> _Window | None:
    if not windows:
        return None
    return min(
        windows,
        key=lambda window: (
            window.cost_eur,
            window.start,
            window.datacenter.datacenter_id,
        ),
    )


def _baseline_window(request: EngineRequest) -> _Window | None:
    datacenter = next(
        (
            item
            for item in request.datacenters
            if item.datacenter_id == request.preferred_datacenter_id
        ),
        None,
    )
    if datacenter is None or datacenter.max_power_kw < request.required_power_kw:
        return None
    return _window_at(
        datacenter,
        request.baseline_start,
        request.duration_minutes,
        request.required_power_kw,
    )


def _recommendation(
    window: _Window,
    baseline: _Window,
    request: EngineRequest,
) -> Recommendation:
    end = window.start + timedelta(minutes=request.duration_minutes)
    baseline_uses_estimated = baseline.uses_estimated_price
    baseline_cost = baseline.cost_eur
    savings = baseline_cost - window.cost_eur
    savings_percent = None if baseline_cost == 0 else savings / baseline_cost * 100
    hourly_costs = [
        HourCost(
            timestamp=hour.timestamp,
            minutes=window.minutes[index],
            price_eur_per_mwh=hour.price_eur_per_mwh,
            temperature_c=hour.temperature_c,
            pue=_pue(window.datacenter.base_pue, hour.temperature_c),
            cost_eur=(
                request.required_power_kw
                * _pue(window.datacenter.base_pue, hour.temperature_c)
                * (window.minutes[index] / 60)
                * hour.price_eur_per_mwh
                * EUR_PER_MWH_TO_EUR_PER_KWH
            ),
            price_is_estimated=hour.price_is_estimated,
        )
        for index, hour in enumerate(window.hours)
    ]
    estimated_energy_kwh = sum(
        request.required_power_kw
        * _pue(window.datacenter.base_pue, hour.temperature_c)
        * (occupied_minutes / 60)
        for hour, occupied_minutes in zip(window.hours, window.minutes)
    )
    return Recommendation(
        target_datacenter=window.datacenter.datacenter_id,
        recommended_start=window.start,
        recommended_end=end,
        estimated_energy_kwh=estimated_energy_kwh,
        estimated_cost_eur=window.cost_eur,
        baseline_cost_eur=baseline_cost,
        estimated_savings_eur=savings,
        estimated_savings_percent=savings_percent,
        is_fallback=window.uses_estimated_price or baseline_uses_estimated,
        hourly_costs=hourly_costs,
        baseline_has_estimated_price=baseline_uses_estimated,
    )


def recommend(request: EngineRequest) -> EngineResponse:
    """Find the cheapest non-preemptive window and an optional estimate.

    The function is deliberately pure: it only validates and calculates from
    the rows supplied by the API. Database access and price estimation belong
    to the API/ETL layer.
    """

    baseline = _baseline_window(request)
    if baseline is None:
        return EngineResponse(
            job_id=request.job_id,
            recommendations=[],
            reason="data_unavailable",
        )

    confirmed = _best_window(_candidate_windows(request, allow_estimated=False))
    all_windows = _candidate_windows(request, allow_estimated=True)
    # The fallback scenario must compare every feasible window.  A real-price
    # window can still be the best available option when the baseline uses an
    # estimated price.
    estimated = _best_window(all_windows)

    if confirmed is not None and not baseline.uses_estimated_price:
        primary = _recommendation(confirmed, baseline, request)
        recommendations = [primary]
        if estimated is not None and (
            estimated.start != confirmed.start
            or estimated.datacenter.datacenter_id != confirmed.datacenter.datacenter_id
        ):
            recommendations.append(_recommendation(estimated, baseline, request))
        return EngineResponse(job_id=request.job_id, recommendations=recommendations)

    if estimated is None:
        return EngineResponse(
            job_id=request.job_id,
            recommendations=[],
            reason="data_unavailable",
        )

    reason = "no_confirmed_window" if confirmed is None else "baseline_estimated"
    return EngineResponse(
        job_id=request.job_id,
        recommendations=[_recommendation(estimated, baseline, request)],
        reason=reason,
    )
