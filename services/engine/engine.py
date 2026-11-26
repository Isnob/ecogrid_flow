"""Pure calculation engine for the K3 recommendation contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

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


@dataclass(frozen=True)
class _Window:
    datacenter: DatacenterInput
    start: datetime
    hours: tuple[HourInput, ...]
    uses_estimated_price: bool
    cost_eur: float


def _pue(base_pue: float, temperature_c: float | None) -> float:
    """Return the hourly PUE from the model documented in docs/research/pue.md."""

    if temperature_c is None or temperature_c <= PUE_FREE_COOLING_LIMIT_C:
        return base_pue
    return base_pue + PUE_WARMING_SLOPE * (
        temperature_c - PUE_FREE_COOLING_LIMIT_C
    )


def _duration_hours(duration_minutes: int) -> int:
    return (duration_minutes + 59) // 60


def _minutes_for_hour(duration_minutes: int, index: int) -> int:
    remaining = duration_minutes - index * 60
    return min(60, remaining)


def _cost_for_hours(
    datacenter: DatacenterInput,
    hours: tuple[HourInput, ...],
    duration_minutes: int,
    required_power_kw: float,
) -> float:
    total = 0.0
    for index, hour in enumerate(hours):
        minutes = _minutes_for_hour(duration_minutes, index)
        pue = _pue(datacenter.base_pue, hour.temperature_c)
        total += (
            required_power_kw
            * pue
            * (minutes / 60)
            * hour.price_eur_per_mwh
            * EUR_PER_MWH_TO_EUR_PER_KWH
        )
    return total


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
    by_timestamp = {hour.timestamp: hour for hour in datacenter.hours}
    hours_count = _duration_hours(duration_minutes)
    selected: list[HourInput] = []
    for index in range(hours_count):
        hour = by_timestamp.get(start + timedelta(hours=index))
        if hour is None:
            return None
        selected.append(hour)
    selected_tuple = tuple(selected)
    return _Window(
        datacenter=datacenter,
        start=start,
        hours=selected_tuple,
        uses_estimated_price=any(hour.price_is_estimated for hour in selected_tuple),
        cost_eur=_cost_for_hours(
            datacenter,
            selected_tuple,
            duration_minutes,
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
        start = request.earliest_start
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
            minutes=_minutes_for_hour(request.duration_minutes, index),
            price_eur_per_mwh=hour.price_eur_per_mwh,
            temperature_c=hour.temperature_c,
            pue=_pue(window.datacenter.base_pue, hour.temperature_c),
            cost_eur=(
                request.required_power_kw
                * _pue(window.datacenter.base_pue, hour.temperature_c)
                * (_minutes_for_hour(request.duration_minutes, index) / 60)
                * hour.price_eur_per_mwh
                * EUR_PER_MWH_TO_EUR_PER_KWH
            ),
            price_is_estimated=hour.price_is_estimated,
        )
        for index, hour in enumerate(window.hours)
    ]
    return Recommendation(
        target_datacenter=window.datacenter.datacenter_id,
        recommended_start=window.start,
        recommended_end=end,
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
    estimated = _best_window(
        [window for window in all_windows if window.uses_estimated_price]
    )

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
            reason="no_confirmed_window" if confirmed is None else "baseline_estimated",
        )

    reason = "no_confirmed_window" if confirmed is None else "baseline_estimated"
    return EngineResponse(
        job_id=request.job_id,
        recommendations=[_recommendation(estimated, baseline, request)],
        reason=reason,
    )
