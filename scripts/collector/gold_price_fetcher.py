#!/usr/bin/env python3
import csv, os, re, subprocess, time
from datetime import datetime
from pathlib import Path

RATE_TTL = 1800
LEAD_SECONDS = 2
RATE_CACHE = None
RATE_TS = 0

def _curl(*args):
    try:
        r = subprocess.run(["curl", "-s", "-m", "10", *args], capture_output=True, timeout=15)
        return r.stdout.decode("utf-8", "ignore") if r.returncode == 0 else ""
    except Exception:
        return ""

def rate():
    global RATE_CACHE, RATE_TS
    now = int(time.time())
    if RATE_CACHE and now - RATE_TS < RATE_TTL: return RATE_CACHE
    m = re.search(r'"CNY"\s*:\s*([0-9.]+)', _curl("https://api.exchangerate-api.com/v4/latest/USD"))
    if m:
        RATE_CACHE, RATE_TS = m.group(1), now
        return RATE_CACHE

def gold_price():
    m = re.search(r'"price"\s*:\s*([0-9.]+)', _curl("-H", "x-access-token: demo", "https://api.gold-api.com/price/XAU"))
    if m: return m.group(1)
    s = _curl("-H", "Referer: https://finance.sina.com.cn/", "https://hq.sinajs.cn/list=hf_GC")
    m = re.search(r'="?([0-9.]+)', s)
    return m.group(1) if m else None

def aligned_time():
    n = datetime.now()
    return f"{n:%H}:{(n.minute // 5) * 5:02d}:00"

def record(price):
    if not price: return
    r = rate()
    if not r: return
    price = f"{float(price):.2f}"
    price_cny = f"{(float(price) / 31.1035) * float(r):.2f}"
    date_str, time_str, month_str = f"{datetime.now():%F}", aligned_time(), f"{datetime.now():%Y-%m}"
    root = Path(__file__).resolve().parents[2]
    file = root / "data" / f"gold_{month_str}.csv"
    file.parent.mkdir(parents=True, exist_ok=True)
    if not file.exists():
        with file.open("w", encoding="utf-8", newline="") as f: csv.writer(f).writerow(["日期", "时间", "金价(USD)", "金价(CNY)"])
    with file.open("a", encoding="utf-8", newline="") as f: csv.writer(f).writerow([date_str, time_str, price, price_cny])
    print(f"✅ 金价已记录: {date_str},{time_str},{price},{price_cny}")

def main():
    while True:
        now = int(time.time())
        nxt = ((now // 300) + 1) * 300
        s = nxt - now - LEAD_SECONDS
        if s > 0: time.sleep(s)
        while int(time.time()) < nxt: time.sleep(0.05)
        print("⏰ 开始查询金价...")
        record(gold_price())

if __name__ == "__main__": main()
