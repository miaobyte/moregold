// GoldView Server — 静态文件 + API代理 + SSE
// 用法: node web/server.mjs [--port 8899]

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { query } from "./src/db.mjs";

const PORT = parseInt(process.argv[process.argv.indexOf("--port") + 1]) || 8899;
const PUBLIC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "public");

// ====== MIME ======
const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript",
  ".css": "text/css",
  ".json": "application/json",
};

// ====== Static file server (React build / SPA fallback) ======
const SPA_EXT = new Set([".html", ".js", ".css", ".svg", ".png", ".ico", ".json", ".woff2"]);

function serveStatic(req, res) {
  const urlPath = req.url === "/" ? "/index.html" : req.url;
  const filePath = path.join(PUBLIC, urlPath);

  // 先试精确匹配
  try {
    const data = fs.readFileSync(filePath);
    const ext = path.extname(filePath);
    res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream", "Cache-Control": "no-cache" });
    res.end(data);
    return true;
  } catch {
    // SPA fallback: 非 API 请求 → index.html
    if (!urlPath.startsWith("/api")) {
      try {
        const data = fs.readFileSync(path.join(PUBLIC, "index.html"));
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end(data);
        return true;
      } catch { return false; }
    }
    return false;
  }
}

// ====== JSON helper ======
function json(res, data, code = 200) {
  res.writeHead(code, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" });
  res.end(JSON.stringify(data));
}

// ====== SSE Stream ======
function handleSSE(req, res) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });

  let last = "";
  const timer = setInterval(async () => {
    try {
      const rows = await query(
        "SELECT dt, price_usd as usd, price_cny as cny FROM gold_prices ORDER BY dt DESC LIMIT 1"
      );
      if (rows.length) {
        const r = rows[0], s = String(r.dt);
        if (s !== last) { last = s; res.write(`data: ${JSON.stringify(r)}\n\n`); }
      }
    } catch { /* ignore */ }
  }, 5000);

  req.on("close", () => clearInterval(timer));
}

// ====== Router ======
// 粒度: 1=1min,5=5min,15=15m,30=30m,60=1h,240=4h,720=12h,1440=1d,10080=1w
function priceSQL(hours, granularity, isRecent, dt) {
  const w = isRecent
    ? `dt >= DATE_SUB(NOW(), INTERVAL ${hours} HOUR)`
    : `dt BETWEEN DATE_SUB('${dt}', INTERVAL ${hours} HOUR) AND DATE_ADD('${dt}', INTERVAL ${hours} HOUR)`;

  // 无聚合: 过滤 mod minute
  if (granularity <= 15) {
    const mod = granularity === 1 ? '' : `AND MOD(minute,${granularity})=0`;
    return `SELECT dt, price_usd as usd, price_cny as cny FROM gold_prices WHERE ${w} ${mod} AND price_usd>0 ORDER BY dt`;
  }
  // 聚合粒度
  const groupMap = {
    30: 'DATE(dt), HOUR(dt), FLOOR(MINUTE(dt)/30)*30',
    60: 'DATE(dt), HOUR(dt)',
    240: 'DATE(dt), FLOOR(HOUR(dt)/4)*4',
    720: 'DATE(dt), FLOOR(HOUR(dt)/12)*12',
    1440: 'DATE(dt)',
    10080: 'YEARWEEK(dt)',
  };
  const group = groupMap[granularity] || 'DATE(dt), HOUR(dt)';
  return `SELECT MIN(dt) as dt, AVG(price_usd) as usd, AVG(price_cny) as cny FROM gold_prices WHERE ${w} AND price_usd>0 GROUP BY ${group} ORDER BY dt`;
}

const routes = {
  "/api/recent": async (url) => {
    const h = parseInt(url.searchParams.get("hours")) || 24;
    const g = parseInt(url.searchParams.get("granularity")) || 1;
    return await query(priceSQL(h, g, true, null));
  },
  "/api/around": async (url) => {
    const dt = url.searchParams.get("dt");
    const h = parseInt(url.searchParams.get("hours")) || 24;
    const g = parseInt(url.searchParams.get("granularity")) || 1;
    return await query(priceSQL(h, g, false, dt));
  },
};

// ====== HTTP Server ======
http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  try {
    if (url.pathname === "/api/stream") return handleSSE(req, res);

    const handler = routes[url.pathname];
    if (handler) {
      const data = await handler(url);
      return json(res, data);
    }

    if (serveStatic(req, res)) return;

    json(res, { error: "Not Found" }, 404);
  } catch (e) {
    json(res, { error: e.message }, 500);
  }
}).listen(PORT, () => console.log(`🥇 GoldView → http://localhost:${PORT}`));
