'use strict';

const assert = require('node:assert/strict');
const {createRecommendationResponse} = require('./mock-api.js');

const response = createRecommendationResponse({
    job_id: 'job-test',
    duration_minutes: 180,
    required_power_kw: 80,
    earliest_start: '2026-11-22T10:00:00.000Z',
    deadline: '2026-11-23T10:00:00.000Z',
    allowed_zones: ['FI', 'SE3', 'DE-LU']
});
assert.equal(response.recommendations.length, 1);
assert.equal(response.recommendations[0].is_fallback, false);
assert.equal(response.recommendations[0].target_datacenter, 'dc-helsinki-1');
assert.equal(response.recommendations[0].recommendation_id, 1);
assert.equal(response.reason, null);
assert.deepEqual(Object.keys(response).sort(), ['job_id', 'reason', 'recommendations', 'search_timelines']);
assert.deepEqual(response.search_timelines.map(item => item.target_datacenter), [
    'dc-helsinki-1',
    'dc-stockholm-1',
    'dc-frankfurt-1'
]);
assert.ok(response.search_timelines.every(item => item.hours.length === 24));
assert.equal(response.search_timelines[0].hours[0].timestamp, '2026-11-22T10:00:00.000Z');
assert.ok(new Date(response.search_timelines[0].hours.at(-1).timestamp) < new Date('2026-11-23T10:00:00.000Z'));
assert.equal(response.recommendations[0].hourly_costs.length, 3);
assert.ok(new Date(response.recommendations[0].recommended_start) >= new Date(response.search_timelines[0].hours[0].timestamp));
assert.ok(new Date(response.recommendations[0].recommended_end) <= new Date('2026-11-23T10:00:00.000Z'));
assert.ok(response.recommendations[0].estimated_cost_eur <= response.recommendations[0].baseline_cost_eur);
assert.ok(!JSON.stringify(response).includes('Оценка, цены ещё не опубликованы'));
console.log('Confirmed recommendation mock: OK');
