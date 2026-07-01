// GoldView Frontend — lightweight-charts + SSE

const { createChart, ColorType } = LightweightCharts;
const COLORS = ['#4fc3f7','#ff7043','#81c784','#ba68c8','#ffd54f','#4dd0e1','#f06292','#aed581','#ff8a65','#90a4ae'];

let mainSeries, chart;
const overlays = [];
window._col = 'usd';

// ====== Chart Init ======
chart = createChart(document.getElementById('chart'), {
  layout: { background: { type: ColorType.Solid, color: '#131722' }, textColor: '#787b86' },
  grid: { vertLines: { color: '#1e222d' }, horzLines: { color: '#1e222d' } },
  crosshair: { mode: 1 },
  rightPriceScale: { borderColor: '#2a2e39' },
  timeScale: { borderColor: '#2a2e39', timeVisible: true, secondsVisible: false },
  handleScroll: { vertTouchDrag: true, horzTouchDrag: true, mouseWheel: true },
  handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
});

// ====== Series helpers ======
function makeSeries(color, dashed) {
  return chart.addLineSeries({
    color, lineWidth: dashed ? 1.5 : 2,
    priceLineVisible: false, lastValueVisible: false,
    crosshairMarkerVisible: true,
    ...(dashed ? { lineStyle: 2 } : {}),
  });
}

async function api(path) {
  const r = await fetch('/api' + path);
  return r.json();
}

// ====== Datetime helpers ======
function setNow() {
  const d = new Date();
  document.getElementById('cmpDate').value = d.toISOString().slice(0, 10);
  document.getElementById('cmpTime').value = d.toISOString().slice(11, 16);
}

function getDatetime() {
  const d = document.getElementById('cmpDate').value;
  const t = document.getElementById('cmpTime').value;
  if (!d) return null;
  return t ? d + ' ' + t + ':00' : d + ' 00:00:00';
}

// ====== Main line (realtime) ======
async function initMain() {
  const mode = document.getElementById('yMode').value;
  window._col = mode;
  const rangeH = parseInt(document.getElementById('rangeH').value);
  const h = Math.max(rangeH, 6);
  const rows = await api('/recent?hours=' + h);
  if (!rows.length) return;

  const data = rows.map(r => ({
    time: Math.floor(new Date(r.dt).getTime() / 1000),
    value: r[mode],
  }));

  mainSeries = makeSeries('#4fc3f7', false);
  mainSeries.setData(data);
  chart.timeScale().fitContent();

  const last = rows[rows.length - 1];
  document.getElementById('pUsd').textContent = last.usd?.toFixed(1) ?? '—';
  document.getElementById('pCny').textContent = last.cny?.toFixed(2) ?? '—';

  startSSE();
}

function startSSE() {
  let lastDt = '';
  const es = new EventSource('/api/stream');
  es.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.dt === lastDt) return;
    lastDt = d.dt;
    const ts = Math.floor(new Date(d.dt).getTime() / 1000);
    if (mainSeries) mainSeries.update({ time: ts, value: d[window._col || 'usd'] });
    document.getElementById('pUsd').textContent = d.usd.toFixed(1);
    document.getElementById('pCny').textContent = d.cny.toFixed(2);
  };
  es.onerror = () => { es.close(); setTimeout(startSSE, 3000); };
}

function switchY() {
  window._col = document.getElementById('yMode').value;
  initMain();
  overlays.forEach(o => loadOverlay(o));
}

// ====== Overlay lines ======
async function addOverlay() {
  const dt = getDatetime();
  if (!dt) return;
  const w = parseInt(document.getElementById('cmpWin').value) || 24;
  const color = COLORS[overlays.length % COLORS.length];
  const label = dt.slice(0, 16);
  overlays.push({ dt, window: w, color, label, series: null, offset: 0, data: null });
  renderTags();
  await loadOverlay(overlays[overlays.length - 1]);
}

async function loadOverlay(o) {
  const mode = document.getElementById('yMode').value;
  const rows = await api('/around?dt=' + encodeURIComponent(o.dt) + '&hours=' + o.window);
  if (!rows.length) return;

  const refTs = new Date(o.dt).getTime() / 1000;
  const shift = Date.now() / 1000 - refTs;
  o.data = rows.map(r => ({
    time: Math.floor(new Date(r.dt).getTime() / 1000) + shift,
    value: r[mode],
  }));

  if (o.series) chart.removeSeries(o.series);
  o.series = makeSeries(o.color, true);
  o.series.setData(applyOffset(o));
}

function applyOffset(o) {
  if (!o.data || !o.offset) return o.data;
  return o.data.map(p => ({ ...p, value: p.value + o.offset }));
}

function updateOverlayData(o) {
  if (!o.series || !o.data) return;
  o.series.setData(applyOffset(o));
  renderTags();
}

function removeOverlay(i) {
  if (overlays[i].series) chart.removeSeries(overlays[i].series);
  overlays.splice(i, 1);
  renderTags();
}

function renderTags() {
  document.getElementById('overlayTags').innerHTML = overlays.map((o, i) =>
    `<div class="ov-tag" style="border-color:${o.color}">
      <span class="dot" style="background:${o.color}"></span>
      ${o.label} ±${o.window}h
      <span style="color:#f0c040">${o.offset ? ' ' + (o.offset > 0 ? '+' : '') + o.offset.toFixed(1) : ''}</span>
      <button class="btn btn-rm" onclick="removeOverlay(${i})">×</button>
    </div>`
  ).join('');
}

// ====== Drag to offset ======
let dragTarget = null, dragStartY = 0, dragStartPrice = 0;

chart.subscribeClick(() => { dragTarget = null; });

document.getElementById('chart').addEventListener('mousedown', e => {
  if (e.button !== 0 || !mainSeries) return;
  const rect = e.target.getBoundingClientRect();
  const x = e.clientX - rect.left, y = e.clientY - rect.top;
  const price = mainSeries.coordinateToPrice(y);
  if (price == null) return;

  let best = null, bestDist = Infinity;
  for (const o of overlays) {
    if (!o.series || !o.data) continue;
    const ts = chart.timeScale().coordinateToTime(x);
    if (ts == null) continue;
    const d = o.data.find(p => p.time >= ts);
    if (!d) continue;
    const linePrice = d.value + (o.offset || 0);
    const dist = Math.abs(price - linePrice);
    if (dist < bestDist) { bestDist = dist; best = o; }
  }
  if (best && bestDist < 20) {
    dragTarget = best; dragStartY = e.clientY; dragStartPrice = price;
    e.preventDefault();
  }
});

window.addEventListener('mousemove', e => {
  if (!dragTarget || !mainSeries) return;
  const price = mainSeries.coordinateToPrice(
    e.clientY - document.getElementById('chart').getBoundingClientRect().top);
  if (price == null) return;
  const delta = price - dragStartPrice;
  dragTarget.offset = (dragTarget.offset || 0) + delta;
  dragStartPrice = price;
  updateOverlayData(dragTarget);
});

window.addEventListener('mouseup', () => { dragTarget = null; });

// ====== Range control ======
function setRange() {
  const rangeH = parseInt(document.getElementById('rangeH').value);
  const from = Math.floor(Date.now() / 1000) - rangeH * 3600;
  chart.timeScale().setVisibleRange({ from, to: Math.floor(Date.now() / 1000) });
}

document.getElementById('rangeH').addEventListener('change', setRange);

// ====== Startup ======
initMain();
