'use strict';

const form = document.querySelector('#taskForm');
const errorBox = document.querySelector('#formError');
const emptyState = document.querySelector('#emptyState');
const resultContent = document.querySelector('#resultContent');
const recommendationsNode = document.querySelector('#recommendations');
const statusNode = document.querySelector('#resultStatus');
const chartNode = document.querySelector('#costChart');
const chartCaption = document.querySelector('#chartCaption');
const chartRange = document.querySelector('#chartRange');
const chartPrevious = document.querySelector('#chartPrevious');
const chartNext = document.querySelector('#chartNext');
const chartWindowLabel = document.querySelector('#chartWindowLabel');
const chartSeriesControls = document.querySelector('#chartSeriesControls');
const chartShowAll = document.querySelector('#chartShowAll');
const mockJson = document.querySelector('#mockJson');

const chartState = {
    timelines: [],
    visibleDatacenters: new Set(),
    primaryDatacenter: null,
    recommendedStart: null,
    recommendedEnd: null,
    startIndex: 0
};

const DATACENTER_PRESENTATION = {
    'dc-helsinki-1': {label: 'Финляндия · Хельсинки', color: '#2785ed'},
    'dc-stockholm-1': {label: 'Швеция · Стокгольм', color: '#8b5cf6'},
    'dc-frankfurt-1': {label: 'Германия · Франкфурт', color: '#f97316'}
};

const pad = value => String(value).padStart(2, '0');
const parseUtcInput = value => new Date(`${value}:00Z`);
const formatUtc = value => `${new Intl.DateTimeFormat('ru-RU', {day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC'}).format(new Date(value))} UTC`;
const formatChartDate = value => new Intl.DateTimeFormat('ru-RU', {day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC'}).format(new Date(value));
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
    const presentation = DATACENTER_PRESENTATION[item.target_datacenter] || {label: item.target_datacenter};
    return `<article class="glass-card recommendation-card primary">
        <div class="recommendation-top"><div>
            <span class="type-badge primary">Основная рекомендация</span>
            <h3 class="recommendation-title">${presentation.label}</h3>
            <span class="recommendation-id">${item.target_datacenter}</span>
        </div><strong>${money(item.estimated_cost_eur)}</strong></div>
        <p class="recommendation-note">Окно рассчитано по подтверждённым ценам.</p>
        <div class="metrics">
            ${metric('Старт', formatUtc(item.recommended_start))}
            ${metric('Завершение', formatUtc(item.recommended_end))}
            ${metric('Экономия', `${money(item.estimated_savings_eur)} · ${Number(item.estimated_savings_percent).toFixed(1)}%`)}
        </div>
    </article>`;
}

function selectedRangeHours() {
    const totalHours = Math.max(0, ...chartState.timelines.map(timeline => timeline.hours.length));
    return chartRange.value === 'all' ? totalHours : Number(chartRange.value);
}

function clampChartStart() {
    const visibleCount = selectedRangeHours();
    const totalHours = Math.max(0, ...chartState.timelines.map(timeline => timeline.hours.length));
    chartState.startIndex = Math.max(0, Math.min(chartState.startIndex, Math.max(0, totalHours - visibleCount)));
}

function svgPoint(index, price, count, minPrice, maxPrice) {
    const width = 920;
    const height = 270;
    const left = 58;
    const right = 18;
    const top = 24;
    const bottom = 45;
    const x = left + (count === 1 ? 0 : index / (count - 1)) * (width - left - right);
    const spread = Math.max(1, maxPrice - minPrice);
    const y = top + (maxPrice - price) / spread * (height - top - bottom);
    return {x, y};
}

function renderChart() {
    if (!chartState.timelines.length) return;
    clampChartStart();

    const totalHours = Math.max(...chartState.timelines.map(timeline => timeline.hours.length));
    const visibleCount = Math.min(selectedRangeHours(), totalHours);
    const visibleTimelines = chartState.timelines.filter(timeline => chartState.visibleDatacenters.has(timeline.target_datacenter));
    const referencePoints = chartState.timelines[0].hours.slice(chartState.startIndex, chartState.startIndex + visibleCount);
    const timelineSlices = visibleTimelines.map(timeline => ({
        ...timeline,
        visibleHours: timeline.hours.slice(chartState.startIndex, chartState.startIndex + visibleCount)
    }));
    const prices = timelineSlices.flatMap(timeline => timeline.visibleHours.map(point => Number(point.price_eur_per_mwh)));
    if (!prices.length || !referencePoints.length) return;
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const width = 920;
    const height = 270;
    const left = 58;
    const right = 18;
    const top = 24;
    const bottom = 45;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const visibleStart = new Date(referencePoints[0].timestamp).getTime();
    const visibleEnd = new Date(referencePoints.at(-1).timestamp).getTime() + 60 * 60 * 1000;
    const visibleDuration = Math.max(1, visibleEnd - visibleStart);
    const recommendedStart = new Date(chartState.recommendedStart).getTime();
    const recommendedEnd = new Date(chartState.recommendedEnd).getTime();
    const highlightStart = Math.max(visibleStart, recommendedStart);
    const highlightEnd = Math.min(visibleEnd, recommendedEnd);
    const highlightX = left + (highlightStart - visibleStart) / visibleDuration * plotWidth;
    const highlightWidth = highlightEnd > highlightStart
        ? Math.max(4, (highlightEnd - highlightStart) / visibleDuration * plotWidth)
        : 0;
    const yTicks = [maxPrice, (maxPrice + minPrice) / 2, minPrice];
    const xTickCount = Math.min(5, referencePoints.length);
    const xTickIndexes = [...new Set(Array.from({length: xTickCount}, (_, index) => Math.round(index * (referencePoints.length - 1) / Math.max(1, xTickCount - 1))))];
    const grid = yTicks.map((value, index) => {
        const y = top + index * plotHeight / 2;
        return `<line class="chart-grid-line" x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"></line><text class="chart-axis-label" x="${left - 10}" y="${y + 4}" text-anchor="end">${value.toFixed(0)}</text>`;
    }).join('');
    const labels = xTickIndexes.map(index => {
        const {x} = svgPoint(index, 0, referencePoints.length, 0, 1);
        const date = new Date(referencePoints[index].timestamp);
        return `<text class="chart-axis-label" x="${x}" y="${height - 15}" text-anchor="middle">${pad(date.getUTCDate())}.${pad(date.getUTCMonth() + 1)} ${pad(date.getUTCHours())}:00</text>`;
    }).join('');
    const series = timelineSlices.map(timeline => {
        const presentation = DATACENTER_PRESENTATION[timeline.target_datacenter] || {label: timeline.target_datacenter, color: '#2785ed'};
        const values = timeline.visibleHours.map(point => Number(point.price_eur_per_mwh));
        const coordinates = values.map((price, index) => svgPoint(index, price, values.length, minPrice, maxPrice));
        const line = coordinates.map((point, index) => `${index ? 'L' : 'M'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
        const hoverPoints = values.length <= 168 ? coordinates.map((point, index) => `<circle class="chart-point" style="stroke:${presentation.color}" cx="${point.x}" cy="${point.y}" r="3"><title>${presentation.label}: ${formatUtc(timeline.visibleHours[index].timestamp)} — ${values[index]} EUR/MWh</title></circle>`).join('') : '';
        return `<path class="price-line" style="stroke:${presentation.color}" d="${line}"></path>${hoverPoints}`;
    }).join('');
    const highlightLabel = highlightWidth > 0
        ? `<text class="recommended-label" x="${Math.min(highlightX + 8, width - 150)}" y="${top + 18}">Выгодное окно</text>`
        : '';

    chartNode.innerHTML = `<svg class="cost-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
        ${grid}
        ${highlightWidth ? `<rect class="recommended-window" x="${highlightX}" y="${top}" width="${highlightWidth}" height="${plotHeight}"></rect>` : ''}
        ${series}${highlightLabel}${labels}
    </svg>`;

    const rangeStart = referencePoints[0].timestamp;
    const rangeEnd = new Date(visibleEnd).toISOString();
    chartWindowLabel.textContent = `${formatChartDate(rangeStart)} — ${formatChartDate(rangeEnd)} UTC`;
    chartPrevious.disabled = chartRange.value === 'all' || chartState.startIndex === 0;
    chartNext.disabled = chartRange.value === 'all' || chartState.startIndex + visibleCount >= totalHours;
    const visibleLabels = visibleTimelines.map(timeline => (DATACENTER_PRESENTATION[timeline.target_datacenter] || {label: timeline.target_datacenter}).label).join(', ');
    chartNode.setAttribute('aria-label', `График цен для ${visibleLabels} с ${formatUtc(rangeStart)} по ${formatUtc(rangeEnd)}. Самое выгодное окно: с ${formatUtc(chartState.recommendedStart)} по ${formatUtc(chartState.recommendedEnd)}.`);
}

function renderSeriesControls() {
    chartSeriesControls.innerHTML = chartState.timelines.map(timeline => {
        const presentation = DATACENTER_PRESENTATION[timeline.target_datacenter] || {label: timeline.target_datacenter, color: '#2785ed'};
        const checked = chartState.visibleDatacenters.has(timeline.target_datacenter) ? 'checked' : '';
        return `<label class="series-toggle" style="--series-color:${presentation.color}">
            <input type="checkbox" value="${timeline.target_datacenter}" ${checked}>
            <i></i><span>${presentation.label}</span>
        </label>`;
    }).join('');

    chartSeriesControls.querySelectorAll('input').forEach(input => input.addEventListener('change', () => {
        if (input.checked) {
            chartState.visibleDatacenters.add(input.value);
        } else if (chartState.visibleDatacenters.size > 1) {
            chartState.visibleDatacenters.delete(input.value);
        } else {
            input.checked = true;
        }
        renderChart();
    }));
    chartShowAll.textContent = chartState.visibleDatacenters.size === chartState.timelines.length ? 'Только рекомендуемый' : 'Показать все';
}

function renderResult(response) {
    emptyState.hidden = true;
    resultContent.hidden = false;
    statusNode.textContent = 'Подтверждённые цены';
    statusNode.classList.remove('warning');
    recommendationsNode.innerHTML = response.recommendations.map(recommendationCard).join('');
    const primaryRecommendation = response.recommendations[0];
    chartState.timelines = response.search_timelines;
    chartState.primaryDatacenter = primaryRecommendation.target_datacenter;
    chartState.visibleDatacenters = new Set([primaryRecommendation.target_datacenter]);
    chartState.recommendedStart = primaryRecommendation.recommended_start;
    chartState.recommendedEnd = primaryRecommendation.recommended_end;
    chartState.startIndex = 0;
    chartRange.value = 'all';
    chartCaption.textContent = `${response.search_timelines.length} ЦОД доступны для сравнения. Рекомендованный интервал выделен на общем графике.`;
    renderSeriesControls();
    renderChart();
    mockJson.textContent = JSON.stringify(response, null, 2);
}

form.addEventListener('submit', event => {
    event.preventDefault();
    const request = readAndValidate();
    if (!request) return;
    renderResult(window.EcoGridMockApi.createRecommendationResponse(request));
});

chartRange.addEventListener('change', () => {
    if (chartRange.value === 'all') {
        chartState.startIndex = 0;
    } else if (chartState.recommendedStart) {
        const primaryTimeline = chartState.timelines.find(timeline => timeline.target_datacenter === chartState.primaryDatacenter);
        const recommendedIndex = primaryTimeline.hours.findIndex(point => new Date(point.timestamp) >= new Date(chartState.recommendedStart));
        chartState.startIndex = Math.max(0, recommendedIndex - Math.floor(selectedRangeHours() / 3));
    }
    renderChart();
});

chartShowAll.addEventListener('click', () => {
    if (chartState.visibleDatacenters.size === chartState.timelines.length) {
        chartState.visibleDatacenters = new Set([chartState.primaryDatacenter]);
    } else {
        chartState.visibleDatacenters = new Set(chartState.timelines.map(timeline => timeline.target_datacenter));
    }
    renderSeriesControls();
    renderChart();
});

chartPrevious.addEventListener('click', () => {
    chartState.startIndex -= Math.max(1, Math.floor(selectedRangeHours() * 0.75));
    renderChart();
});

chartNext.addEventListener('click', () => {
    chartState.startIndex += Math.max(1, Math.floor(selectedRangeHours() * 0.75));
    renderChart();
});
