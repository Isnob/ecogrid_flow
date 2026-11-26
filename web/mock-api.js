(function exposeMockApi(globalScope) {
    'use strict';

    const PRICES_EUR_MWH = [67, 61, 54, 46, 38, 32, 29, 34, 43, 52, 58, 63];
    const DATACENTERS = {
        FI: {id: 'dc-helsinki-1', priceOffset: -5, phase: 0},
        SE3: {id: 'dc-stockholm-1', priceOffset: 1, phase: 2},
        'DE-LU': {id: 'dc-frankfurt-1', priceOffset: 9, phase: 5}
    };

    function addMinutes(value, minutes) {
        return new Date(new Date(value).getTime() + minutes * 60000).toISOString();
    }

    function priceForHour(index, zone) {
        const profile = DATACENTERS[zone];
        const dayOffset = Math.floor(index / 24);
        const basePrice = PRICES_EUR_MWH[(index + profile.phase) % PRICES_EUR_MWH.length];
        return Math.max(12, basePrice + profile.priceOffset + ((dayOffset * 7) % 13) - 6);
    }

    function firstCandidateHour(value) {
        const date = new Date(value);
        const isWholeHour = date.getUTCMinutes() === 0 && date.getUTCSeconds() === 0 && date.getUTCMilliseconds() === 0;
        date.setUTCMinutes(0, 0, 0);
        if (!isWholeHour) date.setUTCHours(date.getUTCHours() + 1);
        return date.toISOString();
    }

    function timelineHour(start, index, zone) {
        const temperatureOffset = zone === 'FI' ? -3 : zone === 'SE3' ? -1 : 2;
        return {
            timestamp: addMinutes(start, index * 60),
            price_eur_per_mwh: priceForHour(index, zone),
            temperature_c: Number((6 + temperatureOffset + Math.sin(index / 4) * 3).toFixed(1)),
            pue: zone === 'FI' ? 1.12 : zone === 'SE3' ? 1.15 : 1.2,
            price_is_estimated: false
        };
    }

    function buildSearchTimeline(request, zone) {
        const startIso = firstCandidateHour(request.earliest_start);
        const start = new Date(startIso).getTime();
        const deadline = new Date(request.deadline).getTime();
        const hours = Math.max(1, Math.ceil((deadline - start) / (60 * 60 * 1000)));
        return {
            target_datacenter: DATACENTERS[zone].id,
            hours: Array.from({length: hours}, (_, index) => timelineHour(startIso, index, zone))
        };
    }

    function windowCost(hours, startIndex, durationMinutes, requiredPowerKw) {
        let minutesLeft = durationMinutes;
        let cost = 0;
        for (let index = startIndex; index < hours.length && minutesLeft > 0; index += 1) {
            const occupiedMinutes = Math.min(60, minutesLeft);
            const hour = hours[index];
            cost += requiredPowerKw * hour.pue * hour.price_eur_per_mwh / 1000 * (occupiedMinutes / 60);
            minutesLeft -= occupiedMinutes;
        }
        return cost;
    }

    function findCheapestWindow(request, timelines) {
        const deadline = new Date(request.deadline).getTime();
        let cheapest = {timeline: timelines[0], index: 0, cost: Number.POSITIVE_INFINITY};
        timelines.forEach(timeline => {
            timeline.hours.forEach((hour, index) => {
                const end = new Date(hour.timestamp).getTime() + request.duration_minutes * 60000;
                if (end > deadline) return;
                const cost = windowCost(timeline.hours, index, request.duration_minutes, request.required_power_kw);
                if (cost < cheapest.cost) cheapest = {timeline, index, cost};
            });
        });
        return cheapest;
    }

    function buildHourlyCosts(request, hours, startIndex) {
        let minutesLeft = request.duration_minutes;
        const result = [];
        for (let index = startIndex; index < hours.length && minutesLeft > 0; index += 1) {
            const hour = hours[index];
            const minutes = Math.min(60, minutesLeft);
            const cost = request.required_power_kw * hour.pue * hour.price_eur_per_mwh / 1000 * (minutes / 60);
            result.push({...hour, minutes, cost_eur: Number(cost.toFixed(4))});
            minutesLeft -= minutes;
        }
        return result;
    }

    function createRecommendationResponse(request) {
        const searchTimelines = request.allowed_zones.map(zone => buildSearchTimeline(request, zone));
        const cheapest = findCheapestWindow(request, searchTimelines);
        const recommendedStart = cheapest.timeline.hours[cheapest.index].timestamp;
        const targetDatacenter = cheapest.timeline.target_datacenter;
        const hourlyCosts = buildHourlyCosts(request, cheapest.timeline.hours, cheapest.index);
        const estimatedCost = hourlyCosts.reduce((sum, point) => sum + point.cost_eur, 0);
        const baselineCost = windowCost(searchTimelines[0].hours, 0, request.duration_minutes, request.required_power_kw);
        const savings = baselineCost - estimatedCost;

        return {
            job_id: request.job_id,
            recommendations: [{
                recommendation_id: 1,
                target_datacenter: targetDatacenter,
                recommended_start: recommendedStart,
                recommended_end: addMinutes(recommendedStart, request.duration_minutes),
                estimated_cost_eur: estimatedCost,
                baseline_cost_eur: baselineCost,
                estimated_savings_eur: savings,
                estimated_savings_percent: baselineCost === 0 ? null : savings / baselineCost * 100,
                is_fallback: false,
                hourly_costs: hourlyCosts
            }],
            reason: null,
            search_timelines: searchTimelines
        };
    }

    const api = {createRecommendationResponse};
    globalScope.EcoGridMockApi = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
