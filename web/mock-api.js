(function exposeMockApi(globalScope) {
    'use strict';

    const PRICES_EUR_MWH = [67, 61, 54, 46, 38, 32, 29, 34, 43, 52, 58, 63];
    const DATACENTERS = {
        FI: 'dc-helsinki-1',
        SE3: 'dc-stockholm-1',
        'DE-LU': 'dc-frankfurt-1'
    };

    function addMinutes(value, minutes) {
        return new Date(new Date(value).getTime() + minutes * 60000).toISOString();
    }

    function createRecommendationResponse(request) {
        const latestStart = new Date(request.deadline).getTime() - request.duration_minutes * 60000;
        const preferredStart = new Date(request.earliest_start).getTime() + 60 * 60000;
        const recommendedStart = new Date(Math.min(preferredStart, latestStart)).toISOString();
        const targetDatacenter = DATACENTERS[request.allowed_zones[0]];

        return {
            status: 'ok',
            job_id: request.job_id,
            recommendations: [{
                recommendation_id: 'rec-confirmed-001',
                job_id: request.job_id,
                target_datacenter: targetDatacenter,
                recommended_start: recommendedStart,
                recommended_end: addMinutes(recommendedStart, request.duration_minutes),
                estimated_cost_eur: 34.72,
                baseline_cost_eur: 51.86,
                estimated_savings_eur: 17.14,
                estimated_savings_percent: 33.05,
                is_fallback: false
            }],
            hourly_costs: PRICES_EUR_MWH.map((price, index) => ({
                time: addMinutes(request.earliest_start, index * 60),
                price_eur_mwh: price
            }))
        };
    }

    const api = {createRecommendationResponse};
    globalScope.EcoGridMockApi = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
