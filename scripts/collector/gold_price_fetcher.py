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
    return f"{n:%H}:{n.minute:02d}:00"


def csv_output(date_str, time_str, price, price_cny, month_str):
    """写入本地 CSV 文件。"""
    root = Path(os.environ.get("GOLD_PROJECT_DIR", Path(__file__).resolve().parents[2]))
    file = root / "data" / f"gold_{month_str}.csv"
    file.parent.mkdir(parents=True, exist_ok=True)
    if not file.exists():
        with file.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow(["日期", "时间", "金价(USD)", "金价(CNY)"])
    with file.open("a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([date_str, time_str, price, price_cny])


def db_output(date_str, time_str, price, price_cny):
    """写入远程 MySQL 数据库。从环境变量 GOLD_DB_URL 获取连接信息。

    环境变量格式:
        GOLD_DB_URL=mysql://user:password@host:port/database
        示例: mysql://root:Abc_014916@bj-cdb-9ermqj8g.sql.tencentcdb.com:26092/gold
    """
    import mysql.connector
    from urllib.parse import urlparse

    url = os.environ.get("GOLD_DB_URL", "")
    if not url:
        return  # 未配置则静默跳过

    try:
        u = urlparse(url)
        config = {
            "host": u.hostname,
            "port": u.port or 3306,
            "user": u.username,
            "password": u.password,
            "database": u.path.lstrip("/"),
            "charset": "utf8mb4",
            "connection_timeout": 5,
        }
    except Exception:
        return

    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
    try:
        conn = mysql.connector.connect(**config)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gold_prices
                (trade_date, trade_time, price_usd, price_cny,
                 weekday, hour, minute, dt, year_week)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                price_usd = VALUES(price_usd),
                price_cny = VALUES(price_cny)
        """, (
            date_str, time_str,
            float(price), float(price_cny),
            dt.weekday(), dt.hour, dt.minute,
            dt.strftime("%Y-%m-%d %H:%M:%S"),
            int(dt.strftime("%Y%U")),
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass  # 写入 DB 失败不影响 CSV 写入和主流程


def record(price):
    if not price: return
    r = rate()
    if not r: return
    price = f"{float(price):.2f}"
    price_cny = f"{(float(price) / 31.1035) * float(r):.2f}"
    date_str, time_str, month_str = f"{datetime.now():%F}", aligned_time(), f"{datetime.now():%Y-%m}"

    db_output(date_str, time_str, price, price_cny)

    print(f"✅ 金价已记录: {date_str},{time_str},{price},{price_cny}")

def main():
    while True:
        now = int(time.time())
        nxt = ((now // 60) + 1) * 60
        s = nxt - now - LEAD_SECONDS
        if s > 0: time.sleep(s)
        while int(time.time()) < nxt: time.sleep(0.05)
        print("⏰ 开始查询金价...")
        record(gold_price())

if __name__ == "__main__": main()
