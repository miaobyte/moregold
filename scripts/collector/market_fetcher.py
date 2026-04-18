#!/usr/bin/env python3
import csv, json, os, subprocess, time
from datetime import datetime
from pathlib import Path

LEAD_SECONDS = int(os.getenv("LEAD_SECONDS", "2"))
INTERVAL_SECONDS = max(5, int(os.getenv("FETCH_INTERVAL_SECONDS", "300")))
ROOT = Path(__file__).resolve().parents[2]


def _curl(url):
    try:
        r = subprocess.run(["curl", "-s", "-m", "10", "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36", "-H", "Accept: application/json", "-H", "Accept-Language: en-US,en;q=0.9", url], capture_output=True, timeout=15)
        return r.stdout.decode("utf-8", "ignore") if r.returncode == 0 else ""
    except Exception:
        return ""


def _write(file, header, row):
    file.parent.mkdir(parents=True, exist_ok=True)
    if not file.exists():
        with file.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow(header)
    with file.open("a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(row)


def fetch_market():
    s = _curl("https://query1.finance.yahoo.com/v7/finance/quote?symbols=%5ETNX,DX-Y.NYB,CL=F")
    print(f"DEBUG: API response length: {len(s)}")
    if len(s) > 0:
        print(f"DEBUG: API response start: {s[:200]}")
    try:
        q = {i.get("symbol"): i.get("regularMarketPrice") for i in json.loads(s).get("quoteResponse", {}).get("result", [])}
        print(f"DEBUG: parsed quotes: {q}")
    except Exception as e:
        print(f"DEBUG: JSON parse error: {e}")
        q = {}
    us10y = q.get("^TNX")
    return (float(us10y) / 10 if us10y is not None else None, q.get("DX-Y.NYB"), q.get("CL=F"))


def record_all(dt):
    d = dt.strftime("%F")
    t = dt.strftime("%H:%M:%S")
    m = dt.strftime("%Y-%m")
    us10y, dxy, oil = fetch_market()
    if us10y is None and dxy is None and oil is None:
        return
    u = f"{float(us10y):.2f}" if us10y is not None else ""
    x = f"{float(dxy):.2f}" if dxy is not None else ""
    o = f"{float(oil):.2f}" if oil is not None else ""
    _write(
        ROOT / "data" / f"market_{m}.csv",
        ["日期", "时间", "美债10Y收益率(%)", "美元指数", "原油价格"],
        [d, t, u, x, o],
    )
    print(f"✅ 市场数据已记录: {d},{t},{u},{x},{o}")


def main():
    print(f"DEBUG: INTERVAL_SECONDS = {INTERVAL_SECONDS}")
    # For testing, run once and exit
    now = int(time.time())
    nxt = now  # Use current time for test
    print(f"DEBUG: now={now}, nxt={nxt}, s=0")
    print("⏰ 开始抓取市场数据...")
    record_all(datetime.fromtimestamp(nxt))


if __name__ == "__main__":
    main()
