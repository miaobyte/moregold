// GoldView — 金价可视化 (Node.js + lightweight-charts)
// 用法: node web/server.mjs [--port 8899]
import http from "node:http";
import mysql from "mysql2/promise";
import { parse } from "node:url";

const PORT = parseInt(process.argv[process.argv.indexOf("--port") + 1]) || 8899;

const pool = mysql.createPool({
  host: "bj-cdb-9ermqj8g.sql.tencentcdb.com", port: 26092,
  user: "gold_ro", password: "BNbQMsn4hhnmuw6P",
  database: "gold", charset: "utf8mb4", connectionLimit: 3,
});

function q(sql, params = []) {
  return pool.execute(sql, params).then(([rows]) => rows);
}

const HTML = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>GoldView - 金价可视化</title>
<script src="https://unpkg.com/lightweight-charts@4.2.2/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#131722;color:#d1d4dc;font-family:-apple-system,system-ui,sans-serif;height:100vh;display:flex;flex-direction:column;overflow:hidden}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:6px 12px;background:#1e222d;border-bottom:1px solid #2a2e39;min-height:38px}
.topbar h1{font-size:15px;color:#f0c040;white-space:nowrap}
.prices{display:flex;gap:14px;font-size:13px}
.prices .usd{color:#4fc3f7}.prices .cny{color:#81c784}
.prices .val{font-weight:700;font-size:15px}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:4px 12px;background:#1e222d;border-bottom:1px solid #2a2e39;font-size:12px}
.controls input,.controls select{background:#2a2e39;color:#d1d4dc;border:1px solid #3a3e4a;padding:3px 6px;border-radius:3px;font-size:12px}
.controls input[type="datetime-local"]{width:175px;color-scheme:dark}
.controls input[type="number"]{width:48px}
.controls label{color:#787b86}
.btn{padding:3px 10px;border:none;border-radius:3px;cursor:pointer;font-size:12px;color:#fff}
.btn-add{background:#1976d2}.btn-add:hover{background:#1565c0}
.btn-rm{background:#c62828;padding:2px 7px;font-size:10px}.btn-rm:hover{background:#b71c1c}
.btn-now{background:#2e7d32}.btn-now:hover{background:#1b5e20}
.overlays{display:flex;gap:6px;flex-wrap:wrap;padding:3px 12px;background:#1e222d;font-size:11px}
.ov-tag{display:flex;align-items:center;gap:5px;background:#2a2e39;padding:2px 7px;border-radius:3px;border-left:3px solid #999}
.ov-tag .dot{width:7px;height:7px;border-radius:50%}
#chart{flex:1;cursor:crosshair}
</style>
</head>
<body>
<div class="topbar">
  <h1>🥇 GoldView</h1>
  <div class="prices" id="prices">
    <span>💰 <span class="usd val" id="pUsd">—</span> USD</span>
    <span>💴 <span class="cny val" id="pCny">—</span> CNY</span>
  </div>
</div>
<div class="controls">
  <label>⏱ 对比</label>
  <input type="date" id="cmpDate"><input type="time" id="cmpTime" step="60">
  <label>±</label><input type="number" id="cmpWin" value="24" min="1" max="168">h
  <button class="btn btn-add" onclick="addOverlay()">+ 添加</button>
  <button class="btn btn-now" onclick="setNow()">📍 现在</button>
  <label style="margin-left:8px">Y轴</label>
  <select id="yMode" onchange="switchY()"><option value="usd">USD/oz</option><option value="cny">CNY/g</option></select>
  <label>范围</label>
  <select id="rangeH" onchange="setRange()">
    <option value="6">6h</option><option value="12">12h</option><option value="24" selected>24h</option><option value="48">2d</option><option value="72">3d</option>
  </select>
</div>
<div class="overlays" id="overlayTags"></div>
<div id="chart"></div>

<script>
const {createChart,ColorType} = LightweightCharts;
const C = ['#4fc3f7','#ff7043','#81c784','#ba68c8','#ffd54f','#4dd0e1','#f06292','#aed581','#ff8a65','#90a4ae'];

const chart = createChart(document.getElementById('chart'), {
  layout:{background:{type:ColorType.Solid,color:'#131722'},textColor:'#787b86'},
  grid:{vertLines:{color:'#1e222d'},horzLines:{color:'#1e222d'}},
  crosshair:{mode:1}, rightPriceScale:{borderColor:'#2a2e39'},
  timeScale:{borderColor:'#2a2e39',timeVisible:true,secondsVisible:false},
  handleScroll:{vertTouchDrag:true,horzTouchDrag:true,mouseWheel:true},
  handleScale:{axisPressedMouseMove:true,mouseWheel:true,pinch:true},
});

let mainSeries, yMode='usd';
const overlays=[];

function setNow(){
  const d=new Date();
  document.getElementById('cmpDate').value=d.toISOString().slice(0,10);
  document.getElementById('cmpTime').value=d.toISOString().slice(11,16);
}
function getDatetime(){
  const d=document.getElementById('cmpDate').value;
  const t=document.getElementById('cmpTime').value;
  if(!d)return null;
  return t?d+' '+t+':00':d+' 00:00:00';
}

function makeSeries(color, dashed){
  return chart.addLineSeries({
    color,lineWidth:2,priceLineVisible:false,lastValueVisible:false,
    crosshairMarkerVisible:true,
    ...(dashed?{lineStyle:2,lineWidth:1.5}:{}),
  });
}

async function api(path){
  const r=await fetch('/api'+path);
  return r.json();
}

// ====== 主线: 实时金价 ======
async function initMain(){
  const mode=document.getElementById('yMode').value;
  const rangeH=parseInt(document.getElementById('rangeH').value);
  const h=Math.max(rangeH,6);
  const rows=await api('/recent?hours='+h);
  if(!rows.length)return;
  const data=rows.map(r=>({time:Math.floor(new Date(r.dt).getTime()/1000),value:r[mode]}));

  // 取 column 名显示
  window._col=mode;

  mainSeries=makeSeries('#4fc3f7',false);
  mainSeries.setData(data);
  chart.timeScale().fitContent();
  
  const last=rows[rows.length-1];
  document.getElementById('pUsd').textContent=last.usd?.toFixed(1)??'—';
  document.getElementById('pCny').textContent=last.cny?.toFixed(2)??'—';

  // SSE 实时更新
  startSSE();
}

function startSSE(){
  let lastDt='';
  const es=new EventSource('/api/stream');
  es.onmessage=e=>{
    const d=JSON.parse(e.data);
    if(d.dt===lastDt)return;lastDt=d.dt;
    const ts=Math.floor(new Date(d.dt).getTime()/1000);
    if(mainSeries)mainSeries.update({time:ts,value:d[window._col||'usd']});
    document.getElementById('pUsd').textContent=d.usd.toFixed(1);
    document.getElementById('pCny').textContent=d.cny.toFixed(2);
  };
  es.onerror=()=>{es.close();setTimeout(startSSE,3000);};
}

function switchY(){
  const mode=document.getElementById('yMode').value;
  window._col=mode;
  // 重建主线
  initMain();
  // 重建 overlays
  overlays.forEach(o=>loadOverlay(o));
}

// ====== 对比线 ======
async function addOverlay(){
  const dt=getDatetime();
  if(!dt)return;
  const w=parseInt(document.getElementById('cmpWin').value)||24;
  const color=C[overlays.length % C.length];
  const label=dt.slice(0,16);
  overlays.push({dt,window:w,color,label,series:null,offset:0,data:null});
  renderTags();
  await loadOverlay(overlays[overlays.length-1]);
}

async function loadOverlay(o){
  const mode=document.getElementById('yMode').value;
  const rows=await api('/around?dt='+encodeURIComponent(o.dt)+'&hours='+o.window);
  if(!rows.length)return;

  const refTs=new Date(o.dt).getTime()/1000;
  const nowTime=Date.now()/1000;
  const shift=nowTime-refTs;
  o.data=rows.map(r=>({time:Math.floor(new Date(r.dt).getTime()/1000)+shift,value:r[mode]}));

  const series=makeSeries(o.color,true);
  series.setData(applyOffset(o));
  if(o.series)chart.removeSeries(o.series);
  o.series=series;
}

function applyOffset(o){
  if(!o.data||!o.offset)return o.data;
  return o.data.map(p=>({...p,value:p.value+o.offset}));
}

function updateOverlayData(o){
  if(!o.series||!o.data)return;
  o.series.setData(applyOffset(o));
  renderTags();
}

function removeOverlay(i){
  const o=overlays[i];
  if(o.series)chart.removeSeries(o.series);
  overlays.splice(i,1);
  renderTags();
}

function renderTags(){
  document.getElementById('overlayTags').innerHTML=overlays.map((o,i)=>
    \`<div class="ov-tag" style="border-color:\${o.color}"><span class="dot" style="background:\${o.color}"></span>\${o.label} ±\${o.window}h <span style="color:#f0c040">\${o.offset?' '+(o.offset>0?'+':'')+o.offset.toFixed(1):''}</span> <button class="btn btn-rm" onclick="removeOverlay(\${i})">×</button></div>\`
  ).join('');
}

// ====== 拖拽线条上下平移 ======
let dragTarget=null, dragStartY=0, dragStartPrice=0;

chart.subscribeClick(()=>{dragTarget=null;});  // 点击取消拖拽

document.getElementById('chart').addEventListener('mousedown',e=>{
  if(e.button!==0||!mainSeries)return;
  const rect=e.target.getBoundingClientRect();
  const x=e.clientX-rect.left, y=e.clientY-rect.top;
  const price=mainSeries.coordinateToPrice(y);
  if(price==null)return;
  let best=null,bestDist=Infinity;
  for(let i=0;i<overlays.length;i++){
    if(!overlays[i].series||!overlays[i].data)continue;
    const ts=chart.timeScale().coordinateToTime(x);
    if(ts==null)continue;
    const d=overlays[i].data.find(p=>p.time>=ts);
    if(!d)continue;
    const linePrice=(d.value+(overlays[i].offset||0));
    const dist=Math.abs(price-linePrice);
    if(dist<bestDist){bestDist=dist;best=overlays[i];}
  }
  if(best&&bestDist<20){
    dragTarget=best;dragStartY=e.clientY;dragStartPrice=price;
    e.preventDefault();
  }
});

window.addEventListener('mousemove',e=>{
  if(!dragTarget||!mainSeries)return;
  const price=mainSeries.coordinateToPrice(
    e.clientY-document.getElementById('chart').getBoundingClientRect().top);
  if(price==null)return;
  const delta=price-dragStartPrice;
  dragTarget.offset=(dragTarget.offset||0)+delta;
  dragStartPrice=price;
  updateOverlayData(dragTarget);
});

window.addEventListener('mouseup',()=>{dragTarget=null;});

function setRange(){
  const rangeH=parseInt(document.getElementById('rangeH').value);
  const from=Math.floor(Date.now()/1000)-rangeH*3600;
  chart.timeScale().setVisibleRange({from,to:Math.floor(Date.now()/1000)});
}

// ====== 启动 ======
document.getElementById('rangeH').addEventListener('change',setRange);
initMain();
</script>
</body>
</html>`;

// ====== HTTP Server ======
http.createServer(async (req, res) => {
  const u = parse(req.url, true);
  const send = (code, type, body) => {
    res.writeHead(code, { "Content-Type": type, "Access-Control-Allow-Origin": "*" });
    res.end(body);
  };

  try {
    if (u.pathname === "/" || u.pathname === "/index.html") {
      send(200, "text/html; charset=utf-8", HTML);
    } else if (u.pathname === "/api/recent") {
      const h = parseInt(u.query.hours) || 24;
      const rows = await q(
        "SELECT dt, price_usd as usd, price_cny as cny FROM gold_prices WHERE dt >= DATE_SUB(NOW(), INTERVAL ? HOUR) AND price_usd > 0 ORDER BY dt", [h]);
      send(200, "application/json", JSON.stringify(rows));
    } else if (u.pathname === "/api/around") {
      const { dt, hours } = u.query;
      const h = parseInt(hours) || 24;
      const rows = await q(
        "SELECT dt, price_usd as usd, price_cny as cny FROM gold_prices WHERE dt BETWEEN DATE_SUB(?, INTERVAL ? HOUR) AND DATE_ADD(?, INTERVAL ? HOUR) AND MOD(minute,5)=0 AND price_usd>0 ORDER BY dt",
        [dt, h, dt, h]);
      send(200, "application/json", JSON.stringify(rows));
    } else if (u.pathname === "/api/stream") {
      res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
      let last = "";
      const timer = setInterval(async () => {
        try {
          const rows = await q("SELECT dt, price_usd as usd, price_cny as cny FROM gold_prices ORDER BY dt DESC LIMIT 1");
          if (rows.length) {
            const r = rows[0]; const s = String(r.dt);
            if (s !== last) { last = s; res.write(`data: ${JSON.stringify(r)}\n\n`); }
          }
        } catch (e) { /* ignore */ }
      }, 5000);
      req.on("close", () => clearInterval(timer));
    } else {
      send(404, "text/plain", "404");
    }
  } catch (e) {
    send(500, "text/plain", String(e));
  }
}).listen(PORT, () => console.log(`🥇 GoldView → http://localhost:${PORT}`));
