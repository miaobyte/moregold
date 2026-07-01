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
  if (!mainSeries) mainSeries = makeSeries('#ffffff', false);
  // 用当前时间范围确定初始粒度, 与缩放逻辑一致
  const rangeH = parseInt(document.getElementById('rangeH').value) || 24;
  currentGranularity = getGranularity(rangeH * 3600);
  await reloadMain(currentGranularity);
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

  const vr = chart.timeScale().getVisibleRange();
  if (o.series) chart.removeSeries(o.series);
  o.series = makeSeries(o.color, true);
  o.series.setData(applyOffset(o));
  if (vr) chart.timeScale().setVisibleRange(vr);
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

// ====== Tooltip ======
const tooltip = document.createElement('div');
Object.assign(tooltip.style, {
  display: 'none', position: 'fixed', top: '42px', right: '12px',
  background: 'rgba(30,34,45,0.93)', border: '1px solid #3a3e4a',
  borderRadius: '4px', padding: '8px 12px', fontSize: '12px',
  zIndex: '1000', pointerEvents: 'none', whiteSpace: 'nowrap',
  boxShadow: '0 2px 10px rgba(0,0,0,0.6)', fontFamily: 'monospace',
  minWidth: "180px",
});
document.body.appendChild(tooltip);

function formatDate(ts) {
  const d = new Date(ts * 1000);
  return (d.getMonth() + 1) + '/' + d.getDate() + ' ' +
    String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

chart.subscribeCrosshairMove(param => {
  if (dragInfo) { tooltip.style.display = 'none'; return; }
  if (!param.time || !param.seriesData || param.seriesData.size === 0) {
    tooltip.style.display = 'none'; return;
  }

  const ov = param.point ? findClosestOverlay(param.point.x, param.point.y + document.getElementById('chart').getBoundingClientRect().top) : null;
  document.getElementById('chart').style.cursor = ov ? 'grab' : 'crosshair';

  const lines = [];
  const time = param.time;
  const sd = param.seriesData;

  const mv = sd.get(mainSeries);
  if (mv != null) {
    const v = mv.value ?? mv.close;
    const cny = v ? (v * 7.0 / 31.1035).toFixed(2) : '\u2014';
    lines.push(['<span style="color:#ffffff">\u25CF</span> <b>实时</b> ' + formatDate(time), (v?.toFixed(1)||'\u2014'), cny]);
  }

  overlays.forEach(o => {
    if (!o.series) return;
    const ov = sd.get(o.series);
    if (ov == null || !o.data) return;
    const v = ov.value ?? ov.close;
    const dp = o.data.find(d => Math.abs((d.time + (o.timeShift || 0)) - time) < 180);
    const usd = v?.toFixed(1) || '\u2014';
    const cny = dp?.cny?.toFixed(2) || (v ? (v * 7.0 / 31.1035).toFixed(2) : '\u2014');
    const origT = dp ? dp.time : time;
    lines.push(['<span style="color:' + o.color + '">\u25CF</span> <b>' + o.label + '</b> ' + formatDate(origT), usd, cny]);
  });

  if (lines.length > 0) {
    const header = '<div style="color:#787b86;font-size:10px;border-bottom:1px solid #3a3e4a;padding-bottom:2px">日期</div>' +
      '<div style="color:#787b86;font-size:10px;border-bottom:1px solid #3a3e4a;padding-bottom:2px;text-align:right">USD</div>' +
      '<div style="color:#787b86;font-size:10px;border-bottom:1px solid #3a3e4a;padding-bottom:2px;text-align:right">CNY</div>';
    const body = lines.map(row =>
      '<div>' + row[0] + '</div>' +
      '<div style="text-align:right">' + row[1] + '</div>' +
      '<div style="text-align:right">' + row[2] + '</div>'
    ).join('');
    tooltip.innerHTML = '<div style="display:grid;grid-template-columns:1fr 72px 72px;gap:1px 10px;align-items:center">' +
      header + body + '</div>';
    tooltip.style.display = 'block';
  } else {
    tooltip.style.display = 'none';
  }
});

document.getElementById('chart').addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });

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
  if (!visibleSec || visibleSec < 0) return 5;
  if (visibleSec < 12 * 3600) return 1;
  if (visibleSec < 3 * 86400) return 5;
  if (visibleSec < 14 * 86400) return 60;
  return 1440;
}

let currentGranularity = 1;
let manualGranularity = 0; // 0=auto, 1/5/60/1440=manual
chart.timeScale().subscribeVisibleTimeRangeChange(async (range) => {
  if (!range || !range.from || !range.to) return;
  if (manualGranularity) return; // 手动模式, 不自动切换
  const span = range.to - range.from;
  if (span < 300 || span > 365 * 86400) return;
  const g = getGranularity(span);
  if (g === currentGranularity) return;
  currentGranularity = g;
  document.getElementById('kline').value = 'auto';
  await reloadMain(g);
  overlays.forEach(o => reloadOverlay(o, g));
});

async function setGranularity() {
  const v = document.getElementById('kline').value;
  if (v === 'auto') {
    manualGranularity = 0;
    // 触发一次自动检测
    const range = chart.timeScale().getVisibleRange();
    if (range) {
      const g = getGranularity(range.to - range.from);
      if (g !== currentGranularity) {
        currentGranularity = g;
        await reloadMain(g);
        overlays.forEach(o => reloadOverlay(o, g));
      }
    }
  } else {
    const g = parseInt(v);
    manualGranularity = g;
    if (g !== currentGranularity) {
      currentGranularity = g;
      await reloadMain(g);
      overlays.forEach(o => reloadOverlay(o, g));
    }
  }
}

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
  const vr3 = chart.timeScale().getVisibleRange();
  mainSeries.setData(data);
  if (vr3) chart.timeScale().setVisibleRange(vr3); else chart.timeScale().fitContent();
  const last = rows[rows.length - 1];
  document.getElementById('pUsd').textContent = last.usd?.toFixed(1) ?? '—';
  document.getElementById('pCny').textContent = last.cny?.toFixed(2) ?? '—';
}

async function reloadOverlay(o, gran) {
  try {
  if (!o.dt || !o.series) return;
  const mode = document.getElementById('yMode').value;
  const rows = await api('/around?dt=' + encodeURIComponent(o.dt) + '&hours=' + o.window + '&granularity=' + gran);
  if (!rows.length) return;
  const ovDate = new Date(o.dt); ovDate.setHours(0, 0, 0, 0);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const dayOffset = Math.round((today - ovDate) / 86400000);
  o.data = rows.map(r => {
    const d = new Date(r.dt); d.setDate(d.getDate() + dayOffset);
    return { time: Math.floor(d.getTime() / 1000), value: Number(r[mode])||0, usd: Number(r.usd)||0, cny: Number(r.cny)||0, origTime: d.getTime() / 1000 };
  });
  const ad = applyOffset(o);
  if (ad.length > 0) o.series.setData(ad);
  } catch(e) { console.error('reloadOverlay error:', e, o); }
}

initMain();
