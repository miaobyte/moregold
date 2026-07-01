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

// ====== Static file server ======
function serveStatic(req, res) {
  let filePath = path.join(PUBLIC, req.url === "/" ? "index.html" : req.url);
  const ext = path.extname(filePath);
  if (!MIME[ext]) return false;

  try {
    const data = fs.readFileSync(filePath);
    res.writeHead(200, { "Content-Type": MIME[ext], "Cache-Control": "no-cache" });
    res.end(data);
    return true;
  } catch {
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
const routes = {
  "/api/recent": async (url) => {
    const h = parseInt(url.searchParams.get("hours")) || 24;
    const rows = await query(
      "SELECT dt, price_usd as usd, price_cny as cny FROM gold_prices WHERE dt >= DATE_SUB(NOW(), INTERVAL ? HOUR) AND price_usd > 0 ORDER BY dt",
      [h]
    );
    return rows;
  },
  "/api/around": async (url) => {
    const dt = url.searchParams.get("dt");
    const h = parseInt(url.searchParams.get("hours")) || 24;
    const rows = await query(
      "SELECT dt, price_usd as usd, price_cny as cny FROM gold_prices WHERE dt BETWEEN DATE_SUB(?, INTERVAL ? HOUR) AND DATE_ADD(?, INTERVAL ? HOUR) AND MOD(minute,5)=0 AND price_usd>0 ORDER BY dt",
      [dt, h, dt, h]
    );
    return rows;
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
