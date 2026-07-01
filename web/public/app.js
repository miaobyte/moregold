// GoldView Frontend — lightweight-charts + SSE + 可拖动对比线

const { createChart, ColorType } = LightweightCharts;
const COLORS = ['#4fc3f7','#ff7043','#81c784','#ba68c8','#ffd54f','#4dd0e1','#f06292','#aed581','#ff8a65','#90a4ae'];

let mainSeries, chart;
const overlays = [];
window._col = 'usd';

// ====== Chart Init ======
chart = createChart(document.getElementById('chart'), {
  layout: { background: { type: ColorType.Solid, color: '#131722' }, textColor: '#787b86' },
  grid: { vertLines: { color: '#1e222d' }, horzLines: { color: '#1e222d' } },
  crosshair: { mode: 0 },
  rightPriceScale: { borderColor: '#2a2e39' },
  timeScale: { borderColor: '#2a2e39', timeVisible: true, secondsVisible: false },
  handleScroll: { vertTouchDrag: true, horzTouchDrag: true, mouseWheel: true },
  handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
});

function makeSeries(color, dashed) {
  return chart.addLineSeries({
    color, lineWidth: dashed ? 2 : 2.5,
    priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
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
  mainSeries = makeSeries('#ffffff', false);
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
  // 时间对齐: 按「同日同时刻」映射到当前日期
  const ovDate = new Date(o.dt);
  ovDate.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const dayOffset = Math.round((today - ovDate) / 86400000);

  o.data = rows.map(r => {
    const d = new Date(r.dt);
    d.setDate(d.getDate() + dayOffset);
    return { time: Math.floor(d.getTime() / 1000), value: r[mode] };
  });

  if (o.series) chart.removeSeries(o.series);
  o.series = makeSeries(o.color, true);
  o.series.setData(applyOffset(o));
  addMarkers(o);
}

function applyOffset(o) {
  if (!o.data) return [];
  const ts = o.timeShift || 0;
  const po = o.offset || 0;
  return o.data.map(p => ({ time: p.time + ts, value: p.value + po }));
}

// 在线条上添加可拖动的圆点标记
function addMarkers(o) {
  if (!o.series || !o.data || !o.data.length) return;
  const mid = o.data[Math.floor(o.data.length / 2)];
  const ts = o.timeShift || 0;
  o.series.setMarkers([{
    time: mid.time + ts,
    position: 'inBar',
    color: o.color,
    shape: 'circle',
    size: 2,
  }]);
}

async function refetchOverlay(o, newDt) {
  o.dt = newDt;
  o.label = newDt.slice(0, 16);
  await loadOverlay(o);
}

// ====== 按钮控制: 精确调节 ======
function shiftOverlayTime(i, hours) {
  const o = overlays[i];
  if (!o) return;
  o.timeShift = (o.timeShift || 0) + hours * 3600;
  updateOverlayData(o);

  // 偏移超过阈值时重新获取数据并重置 shift
  if (Math.abs(o.timeShift) >= 7200) {
    const totalH = o.timeShift / 3600;
    const newDt = shiftDatetime(o.dt, Math.round(totalH));
    o.timeShift = 0;
    refetchOverlay(o, newDt);
  }
}

function shiftOverlayPrice(i, delta) {
  const o = overlays[i];
  if (!o) return;
  o.offset = (o.offset || 0) + delta;
  updateOverlayData(o);
}

function updateOverlayData(o) {
  if (!o.series || !o.data) return;
  o.series.setData(applyOffset(o));
  addMarkers(o);
  renderTags();
}

function removeOverlay(i) {
  if (overlays[i].series) chart.removeSeries(overlays[i].series);
  overlays.splice(i, 1);
  renderTags();
}

function renderTags() {
  document.getElementById('overlayTags').innerHTML = overlays.map((o, i) => {
    const info = [];
    if (o.timeShift) info.push(`Δt${(o.timeShift >= 0 ? '+' : '')}${(o.timeShift / 3600).toFixed(1)}h`);
    if (o.offset) info.push(`${(o.offset >= 0 ? '+' : '')}${o.offset.toFixed(1)}`);
    const txt = info.length ? ' <span style="color:#f0c040">' + info.join(' ') + '</span>' : '';
    return `<div class="ov-tag" style="border-color:${o.color}">
      <span class="dot" style="background:${o.color};cursor:grab" title="拖动线条或按钮调节"></span>
      ${o.label} ±${o.window}h${txt}
      <button class="btn" style="background:#1a237e;padding:2px 5px;font-size:10px" onclick="shiftOverlayTime(${i},-1)" title="左移1小时">◀</button>
      <button class="btn" style="background:#1a237e;padding:2px 5px;font-size:10px" onclick="shiftOverlayTime(${i},1)" title="右移1小时">▶</button>
      <button class="btn" style="background:#1b5e20;padding:2px 5px;font-size:10px" onclick="shiftOverlayPrice(${i},5)" title="上移5美元">▲</button>
      <button class="btn" style="background:#1b5e20;padding:2px 5px;font-size:10px" onclick="shiftOverlayPrice(${i},-5)" title="下移5美元">▼</button>
      <button class="btn btn-rm" onclick="removeOverlay(${i})">×</button>
    </div>`;
  }).join('');
}

// ====== 鼠标拖动 ======
let dragInfo = null;

function findClosestOverlay(x, y) {
  const chartEl = document.getElementById('chart');
  const rect = chartEl.getBoundingClientRect();
  const relX = x - rect.left, relY = y - rect.top;
  const price = mainSeries?.coordinateToPrice(relY);
  const time = chart.timeScale().coordinateToTime(relX);
  if (price == null || time == null) return null;

  let best = null, bestDist = Infinity;
  for (const o of overlays) {
    if (!o.series || !o.data || !o.data.length) continue;
    for (const d of o.data) {
      const t = d.time + (o.timeShift || 0);
      const p = d.value + (o.offset || 0);
      const dt = Math.abs(t - time);
      const dp = Math.abs(p - price);
      // 接近度 = 时间差(秒) + 价格差(USD)
      const score = dt * 0.01 + dp;
      if (score < bestDist && dt < 3600 && dp < 20) {
        bestDist = score; best = o;
      }
    }
  }
  return best && bestDist < 15 ? best : null; // lower = closer
}

chart.subscribeCrosshairMove(param => {
  if (!param.point || dragInfo) return;
  const ov = findClosestOverlay(param.point.x, param.point.y + document.getElementById('chart').getBoundingClientRect().top);
  document.getElementById('chart').style.cursor = ov ? 'grab' : 'crosshair';
});

document.getElementById('chart').addEventListener('mousedown', e => {
  if (e.button !== 0 || !mainSeries) return;
  const ov = findClosestOverlay(e.clientX, e.clientY);
  if (!ov) return;

  const rect = document.getElementById('chart').getBoundingClientRect();
  const relX = e.clientX - rect.left, relY = e.clientY - rect.top;
  const price = mainSeries.coordinateToPrice(relY);
  const time = chart.timeScale().coordinateToTime(relX);

  dragInfo = {
    ov, startX: e.clientX, startY: e.clientY,
    startPrice: price, startTime: time,
    initOffset: ov.offset || 0,
    initTimeShift: ov.timeShift || 0,
    initDt: ov.dt,
    lastFetch: 0,
    idx: overlays.indexOf(ov),
  };
  document.getElementById('chart').style.cursor = 'grabbing';
  e.preventDefault();
  e.stopPropagation();
}, true);

window.addEventListener('mousemove', e => {
  if (!dragInfo || !mainSeries) return;
  const ov = dragInfo.ov;
  const rect = document.getElementById('chart').getBoundingClientRect();
  const relX = e.clientX - rect.left, relY = e.clientY - rect.top;

  const curPrice = mainSeries.coordinateToPrice(relY);
  const curTime = chart.timeScale().coordinateToTime(relX);

  const pDelta = curPrice != null ? curPrice - dragInfo.startPrice : 0;
  const tDelta = curTime != null ? curTime - dragInfo.startTime : 0;

  ov.offset = dragInfo.initOffset + pDelta;
  ov.timeShift = dragInfo.initTimeShift + tDelta;

  // 时间偏移超过阈值 → 重新获取数据
  const tH = ov.timeShift / 3600;
  if (Math.abs(tH) >= 2 && Date.now() - dragInfo.lastFetch > 1500) {
    const newDt = shiftDatetime(dragInfo.initDt, Math.round(tH));
    dragInfo.lastFetch = Date.now();
    dragInfo.initDt = newDt;
    dragInfo.initTimeShift = 0;
    ov.timeShift = 0;
    dragInfo.startTime = curTime;
    refetchOverlay(ov, newDt);
  } else {
    ov.series.setData(applyOffset(ov));
    addMarkers(ov);
  }
  renderTags();
});

window.addEventListener('mouseup', () => {
  if (dragInfo) document.getElementById('chart').style.cursor = 'crosshair';
  dragInfo = null;
});

// ====== Range ======
function setRange() {
  const rangeH = parseInt(document.getElementById('rangeH').value);
  const from = Math.floor(Date.now() / 1000) - rangeH * 3600;
  chart.timeScale().setVisibleRange({ from, to: Math.floor(Date.now() / 1000) });
}

document.getElementById('rangeH').addEventListener('change', setRange);


// ====== 缩放自动切换粒度 ======
function getGranularity(visibleSec) {
  if (visibleSec < 12 * 3600) return 1;
  if (visibleSec < 3 * 86400) return 5;
  if (visibleSec < 14 * 86400) return 60;
  return 1440;
}

let currentGranularity = 1;
chart.timeScale().subscribeVisibleTimeRangeChange(async (range) => {
  if (!range) return;
  const g = getGranularity(range.to - range.from);
  if (g === currentGranularity) return;
  currentGranularity = g;
  await reloadMain(g);
  overlays.forEach(o => reloadOverlay(o, g));
});

async function reloadMain(gran) {
  const mode = document.getElementById('yMode').value;
  const rangeH = parseInt(document.getElementById('rangeH').value);
  const h = Math.max(rangeH, 6);
  const rows = await api('/recent?hours=' + h + '&granularity=' + gran);
  if (!rows.length) return;
  const data = rows.map(r => ({
    time: Math.floor(new Date(r.dt).getTime() / 1000),
    value: r[mode], usd: r.usd, cny: r.cny,
  }));
  mainSeries.setData(data);
}

async function reloadOverlay(o, gran) {
  if (!o.dt) return;
  const mode = document.getElementById('yMode').value;
  const rows = await api('/around?dt=' + encodeURIComponent(o.dt) + '&hours=' + o.window + '&granularity=' + gran);
  if (!rows.length) return;
  const ovDate = new Date(o.dt); ovDate.setHours(0, 0, 0, 0);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const dayOffset = Math.round((today - ovDate) / 86400000);
  o.data = rows.map(r => {
    const d = new Date(r.dt); d.setDate(d.getDate() + dayOffset);
    return { time: Math.floor(d.getTime() / 1000), value: r[mode], usd: r.usd, cny: r.cny, origTime: d.getTime() / 1000 };
  });
  if (o.series) o.series.setData(applyOffset(o));
}

initMain();
