// GoldView Frontend — lightweight-charts + SSE + 双轴拖动

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
  handleScroll: { vertTouchDrag: false, horzTouchDrag: false, mouseWheel: true },
  handleScale: { axisPressedMouseMove: { price: false, time: false }, mouseWheel: true, pinch: true },
});

function makeSeries(color, dashed) {
  return chart.addLineSeries({
    color, lineWidth: dashed ? 1.5 : 2,
    priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: true,
    ...(dashed ? { lineStyle: 2 } : {}),
  });
}

async function api(path) {
  const r = await fetch('/api' + path);
  return r.json();
}

// ====== Input helpers ======
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

function shiftDatetime(dtStr, h) {
  const d = new Date(dtStr);
  d.setHours(d.getHours() + Math.round(h));
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:00`;
}

// ====== Main line ======
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

  if (mainSeries) chart.removeSeries(mainSeries);
  mainSeries = makeSeries('#4fc3f7', false);
  mainSeries.setData(data);
  chart.timeScale().fitContent();

  const last = rows[rows.length - 1];
  document.getElementById('pUsd').textContent = last.usd?.toFixed(1) ?? '—';
  document.getElementById('pCny').textContent = last.cny?.toFixed(2) ?? '—';

  startSSE();
}

function startSSE() {
  if (window._sse) window._sse.close();
  let lastDt = '';
  const es = new EventSource('/api/stream');
  window._sse = es;
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

// ====== Overlay CRUD ======
async function addOverlay() {
  const dt = getDatetime();
  if (!dt) return;
  const w = parseInt(document.getElementById('cmpWin').value) || 24;
  const color = COLORS[overlays.length % COLORS.length];
  overlays.push({ dt, window: w, color, label: dt.slice(0, 16), series: null, offset: 0, timeShift: 0, data: null });
  renderTags();
  await loadOverlay(overlays[overlays.length - 1]);
}

async function loadOverlay(o) {
  const mode = document.getElementById('yMode').value;
  const rows = await api('/around?dt=' + encodeURIComponent(o.dt) + '&hours=' + o.window);
  if (!rows.length) return;
  o.data = rows.map(r => ({
    time: Math.floor(new Date(r.dt).getTime() / 1000),
    value: r[mode],
  }));
  if (o.series) chart.removeSeries(o.series);
  o.series = makeSeries(o.color, true);
  o.series.setData(applyOffset(o));
}

function applyOffset(o) {
  if (!o.data) return [];
  const ts = o.timeShift || 0;
  const po = o.offset || 0;
  return o.data.map(p => ({ time: p.time + ts, value: p.value + po }));
}

async function refetchOverlay(o, newDt) {
  o.dt = newDt;
  o.label = newDt.slice(0, 16);
  await loadOverlay(o);
}

function removeOverlay(i) {
  if (overlays[i].series) chart.removeSeries(overlays[i].series);
  overlays.splice(i, 1);
  renderTags();
}

function renderTags() {
  document.getElementById('overlayTags').innerHTML = overlays.map((o, i) => {
    const parts = [];
    if (o.timeShift) parts.push(`Δt${(o.timeShift >= 0 ? '+' : '')}${(o.timeShift / 3600).toFixed(1)}h`);
    if (o.offset) parts.push(`${(o.offset >= 0 ? '+' : '')}${o.offset.toFixed(1)}`);
    const info = parts.length ? parts.join(' ') : '';
    return `<div class="ov-tag" style="border-color:${o.color}">
      <span class="dot" style="background:${o.color}"></span>
      ${o.label} ±${o.window}h
      <span style="color:#f0c040">${info}</span>
      <button class="btn btn-rm" onclick="removeOverlay(${i})">×</button>
    </div>`;
  }).join('');
}

// ====== 双轴拖动 ======
// 水平拖动 → 重新获取该线条时间窗口的数据
// 垂直拖动 → 所有 overlay 线条整体平移价格
let drag = null;

function findClosestOverlay(x, y) {
  const price = mainSeries.coordinateToPrice(y);
  const time = chart.timeScale().coordinateToTime(x);
  if (price == null || time == null) return null;

  let best = null, bestDist = Infinity;
  for (const o of overlays) {
    if (!o.series || !o.data || !o.data.length) continue;
    const d = o.data.find(p => (p.time + (o.timeShift || 0)) >= time);
    if (!d) continue;
    const lp = d.value + (o.offset || 0);
    const dist = Math.abs(price - lp);
    if (dist < bestDist) { bestDist = dist; best = o; }
  }
  return best && bestDist < 25 ? best : null;
}

document.getElementById('chart').addEventListener('mousedown', e => {
  if (e.button !== 0 || !mainSeries) return;
  const rect = e.target.getBoundingClientRect();
  const ov = findClosestOverlay(e.clientX - rect.left, e.clientY - rect.top);
  if (!ov) return;

  const price = mainSeries.coordinateToPrice(e.clientY - rect.top);
  const time = chart.timeScale().coordinateToTime(e.clientX - rect.left);

  drag = {
    overlay: ov,
    startX: e.clientX, startY: e.clientY,
    startPrice: price, startTime: time,
    // 快照: 所有线条的初始偏移
    snapshots: overlays.map(o => ({ offset: o.offset || 0, timeShift: o.timeShift || 0 })),
    initDt: ov.dt,
    initTimeShift: ov.timeShift || 0,
    lastFetchH: 0,
  };
  e.preventDefault();
});

window.addEventListener('mousemove', e => {
  if (!drag || !mainSeries) return;
  const rect = document.getElementById('chart').getBoundingClientRect();
  const ov = drag.overlay;

  // ---- 垂直: 所有线条整体价格平移 ----
  const curPrice = mainSeries.coordinateToPrice(e.clientY - rect.top);
  if (curPrice != null) {
    const pDelta = curPrice - drag.startPrice;
    overlays.forEach((o, i) => {
      o.offset = drag.snapshots[i].offset + pDelta;
    });
  }

  // ---- 水平: 目标线条时间偏移 / 重新获取数据 ----
  const curTime = chart.timeScale().coordinateToTime(e.clientX - rect.left);
  if (curTime != null) {
    const tDeltaSec = curTime - drag.startTime;
    const tDeltaH = tDeltaSec / 3600;
    ov.timeShift = drag.initTimeShift + tDeltaSec;

    // 超过 2 小时且距上次请求 >1.5s → 重新加载
    if (Math.abs(tDeltaH) >= 2 && Date.now() - drag.lastFetchH > 1500) {
      const newDt = shiftDatetime(drag.initDt, Math.round(tDeltaH));
      drag.lastFetchH = Date.now();
      drag.initDt = newDt;
      drag.initTimeShift = 0;
      ov.timeShift = 0;
      // 更新快照
      drag.snapshots = overlays.map(o => ({
        offset: o.offset || 0,
        timeShift: o.timeShift || 0,
      }));
      refetchOverlay(ov, newDt);
    }
  }

  // 批量更新所有线条
  overlays.forEach(o => { if (o.series && o.data) o.series.setData(applyOffset(o)); });
  renderTags();
});

window.addEventListener('mouseup', () => { drag = null; });

// ====== Range ======
function setRange() {
  const rangeH = parseInt(document.getElementById('rangeH').value);
  const from = Math.floor(Date.now() / 1000) - rangeH * 3600;
  chart.timeScale().setVisibleRange({ from, to: Math.floor(Date.now() / 1000) });
}

document.getElementById('rangeH').addEventListener('change', setRange);

// ====== Startup ======
initMain();
