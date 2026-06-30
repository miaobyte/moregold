#!/usr/bin/env python3
"""下载 ETF 数据并导入 world_event. 用法: python scripts/download_etf.py

环境变量:
    GOLD_DB_HOST  — MySQL 主机
    GOLD_DB_PORT  — MySQL 端口
    GOLD_DB_USER  — MySQL 用户名
    GOLD_DB_PASS  — MySQL 密码
    GOLD_DB_NAME  — MySQL 数据库名
"""
import time, json, os, urllib.request, mysql.connector, pandas as pd

ETF_LIST = {
    '107.GLD': ('GOLD_ETF_PRICE_HKD', 'GLD ETF港股价格(HKD)'),
}

def download_eastmoney(secid, max_retries=5):
    url = (f'https://push2his.eastmoney.com/api/qt/stock/kline/get?'
           f'secid={secid}&fields1=f1,f2&fields2=f51,f52,f53'
           f'&klt=101&fqt=0&beg=20191201&end=20260630')
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
               'Referer': 'https://quote.eastmoney.com/'}
    for i in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            klines = data['data']['klines']
            dates, closes = [], []
            for line in klines:
                p = line.split(',')
                dates.append(p[0])
                closes.append(float(p[2]))
            return pd.Series(closes, index=pd.to_datetime(dates))
        except Exception as e:
            wait = 30 * (2 ** i)
            print(f'  retry {i+1}/{max_retries} in {wait}s: {e}')
            time.sleep(wait)
    return None

def import_events(series, event_type, threshold=None):
    series = series.sort_index()
    series = series[~series.index.duplicated(keep='last')]
    if threshold is None:
        threshold = series.diff().dropna().std()

    conn = mysql.connector.connect(
        host=os.environ.get("GOLD_DB_HOST", "localhost"),
        port=int(os.environ.get("GOLD_DB_PORT", "3306")),
        user=os.environ.get("GOLD_DB_USER", "root"),
        password=os.environ.get("GOLD_DB_PASS", ""),
        database=os.environ.get("GOLD_DB_NAME", "gold"),
        charset="utf8mb4", connection_timeout=30)
    cur = conn.cursor()

    prev, rows = None, []
    for dt, val in series.items():
        if pd.isna(val): continue
        if prev is None or abs(val - prev) >= threshold:
            dt_str = dt.strftime('%Y-%m-%d 00:00:00')
            diff = val - prev if prev else 0
            sev = 1
            if abs(diff) >= 2*threshold: sev = 3
            if abs(diff) >= 3*threshold: sev = 5
            rows.append((dt_str, event_type, float(val), sev, 'AUTO', 0.0,
                        f'{prev:.2f}→{val:.2f}' if prev else f'{val:.2f}'))
            prev = val

    cur.executemany(
        "INSERT INTO world_event (event_dt, event_type, event_value, severity, source, predictability, cause_detail) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)", rows)
    conn.commit()
    n = len(rows)
    cur.close(); conn.close()
    return n

if __name__ == '__main__':
    for secid, (event_type, label) in ETF_LIST.items():
        print(f'📥 {label} ({secid})...')
        series = download_eastmoney(secid)
        if series is None:
            print(f'  ❌ 下载失败')
            continue
        print(f'  ✅ {len(series)} rows [{series.index[0].date()}, {series.index[-1].date()}]')
        os.makedirs('data/macro/individual', exist_ok=True)
        series.to_csv(f'data/macro/individual/em_{event_type.lower()}.csv', header=True)
        print(f'  💾 已缓存')

        n = import_events(series, event_type)
        print(f'  ✅ 导入 world_event: {n}条')
        time.sleep(60)  # 请求间隔, 避免限频
