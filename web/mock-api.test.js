'use strict';

const assert = require('node:assert/strict');
const {createRecommendationResponse} = require('./mock-api.js');

const response = createRecommendationResponse({
    job_id: 'job-test',
    duration_minutes: 180,
    required_power_kw: 80,
    earliest_start: '2026-11-22T10:00:00.000Z',
    deadline: '2026-11-23T10:00:00.000Z',
    allowed_zones: ['FI']
});

assert.equal(response.status, 'ok');
assert.equal(response.recommendations.length, 1);
assert.equal(response.recommendations[0].is_fallback, false);
assert.equal(response.recommendations[0].target_datacenter, 'dc-helsinki-1');
assert.ok(!JSON.stringify(response).includes('Оценка, цены ещё не опубликованы'));
console.log('Confirmed recommendation mock: OK');
