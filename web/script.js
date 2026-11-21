'use strict';

const form = document.querySelector('#taskForm');
const errorBox = document.querySelector('#formError');
const emptyState = document.querySelector('#emptyState');
const resultContent = document.querySelector('#resultContent');
const recommendationsNode = document.querySelector('#recommendations');
const statusNode = document.querySelector('#resultStatus');
const chartNode = document.querySelector('#costChart');
const chartCaption = document.querySelector('#chartCaption');
const mockJson = document.querySelector('#mockJson');

const pad = value => String(value).padStart(2, '0');
const parseUtcInput = value => new Date(`${value}:00Z`);
const formatUtc = value => `${new Intl.DateTimeFormat('ru-RU', {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC'}).format(new Date(value))} UTC`;
const money = value => new Intl.NumberFormat('ru-RU', {style: 'currency', currency: 'EUR'}).format(value);

function clearValidation() {
    errorBox.hidden = true;
    errorBox.textContent = '';
    form.querySelectorAll('.input-invalid').forEach(node => node.classList.remove('input-invalid'));
}

function invalidate(message, fields = []) {
    errorBox.textContent = message;
    errorBox.hidden = false;
    fields.forEach(id => document.querySelector(`#${id}`)?.classList.add('input-invalid'));
    document.querySelector(`#${fields[0]}`)?.focus();
    return null;
}

function readAndValidate() {
    clearValidation();
    const taskName = document.querySelector('#taskName').value.trim();
    const durationHours = Number(document.querySelector('#duration').value);
    const power = Number(document.querySelector('#power').value);
    const deadline = parseUtcInput(document.querySelector('#deadline').value);
    const zones = [...form.querySelectorAll('[name="allowed_zones"]:checked')].map(node => node.value);
    const earliestStart = new Date();
    earliestStart.setUTCMinutes(0, 0, 0);

    if (!taskName) return invalidate('Укажите название задачи.', ['taskName']);
    if (!Number.isFinite(durationHours) || durationHours <= 0) return invalidate('Длительность должна быть больше нуля.', ['duration']);
    if (!Number.isFinite(power) || power <= 0) return invalidate('Мощность должна быть больше нуля.', ['power']);
    if (Number.isNaN(deadline.getTime())) return invalidate('Укажите дедлайн выполнения.', ['deadline']);
    if (deadline.getTime() < earliestStart.getTime() + durationHours * 60 * 60 * 1000) {
        return invalidate('Дедлайн недостижим: времени до него меньше длительности задачи.', ['duration', 'deadline']);
    }
    if (!zones.length) return invalidate('Выберите хотя бы один доступный регион.');
    if (!form.reportValidity()) return null;

    return {
        job_id: `job-${Date.now()}`,
        task_name: taskName,
        duration_minutes: durationHours * 60,
        required_power_kw: power,
        earliest_start: earliestStart.toISOString(),
        deadline: deadline.toISOString(),
        allowed_zones: zones
    };
}

function metric(label, value) {
    return `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`;
}

function recommendationCard(item) {
    return `<article class="glass-card recommendation-card primary">
        <div class="recommendation-top"><div>
            <span class="type-badge primary">Основная рекомендация</span>
            <h3 class="recommendation-title">${item.target_datacenter}</h3>
        </div><strong>${money(item.estimated_cost_eur)}</strong></div>
        <p class="recommendation-note">Окно рассчитано по подтверждённым ценам.</p>
        <div class="metrics">
            ${metric('Старт', formatUtc(item.recommended_start))}
            ${metric('Завершение', formatUtc(item.recommended_end))}
            ${metric('Экономия', `${money(item.estimated_savings_eur)} · ${Number(item.estimated_savings_percent).toFixed(1)}%`)}
        </div>
    </article>`;
}

function renderChart(points) {
    const max = Math.max(...points.map(point => Number(point.price_eur_mwh)));
    chartNode.innerHTML = points.map(point => {
        const price = Number(point.price_eur_mwh);
        const height = Math.max(8, price / max * 82);
        const hour = new Date(point.time).getUTCHours();
        return `<div class="bar-wrap" title="${pad(hour)}:00 — ${price} EUR/MWh"><span class="bar-value">${price}</span><div class="bar" style="height:${height}%"></div><span class="bar-label">${pad(hour)}:00</span></div>`;
    }).join('');
}

function renderResult(response) {
    emptyState.hidden = true;
    resultContent.hidden = false;
    statusNode.textContent = 'Подтверждённые цены';
    statusNode.classList.remove('warning');
    recommendationsNode.innerHTML = response.recommendations.map(recommendationCard).join('');
    chartCaption.textContent = 'Подтверждённые Day-Ahead цены для выбранного окна.';
    renderChart(response.hourly_costs);
    mockJson.textContent = JSON.stringify(response, null, 2);
    resultContent.scrollIntoView({behavior: 'smooth', block: 'start'});
}

form.addEventListener('submit', event => {
    event.preventDefault();
    const request = readAndValidate();
    if (!request) return;
    renderResult(window.EcoGridMockApi.createRecommendationResponse(request));
});
