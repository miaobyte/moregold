#!/usr/bin/env python3
import argparse
import re
import time
from datetime import datetime
from pathlib import Path

DATE_RE = re.compile(r"gold_(\d{4}-\d{2}-\d{2})\.csv$")

def latest_csv(dir_path: Path):
    files = sorted(dir_path.glob("gold_*.csv"))
    return files[-1] if files else None

def parse_last_row(path: Path):
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(lines) < 2:
        return None
    prices = [float(l.split(",")[2].split()[0]) for l in lines[1:] if "," in l]
    time_str, usd_str, cny_str = lines[-1].split(",")
    cny = float(cny_str.split()[0])
    m = DATE_RE.search(path.name)
    date_str = m.group(1) if m else datetime.now().strftime("%Y-%m-%d")
    stamp = f"{date_str} {time_str}"
    return stamp, time_str, cny, usd_str, prices

def sma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None

def rsi(vals, n=14):
    if len(vals) < n + 1:
        return None
    diffs = [vals[i] - vals[i - 1] for i in range(len(vals) - n, len(vals))]
    gains = sum(d for d in diffs if d > 0)
    losses = -sum(d for d in diffs if d < 0)
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - 100 / (1 + rs)

def atr(vals, n=14):
    if len(vals) < n + 1:
        return None
    diffs = [abs(vals[i] - vals[i - 1]) for i in range(len(vals) - n, len(vals))]
    return sum(diffs) / n

def bollinger(vals, n=20, k=2):
    if len(vals) < n:
        return None
    window = vals[-n:]
    mean = sum(window) / n
    var = sum((x - mean) ** 2 for x in window) / n
    sd = var ** 0.5
    return mean, mean + k * sd, mean - k * sd

def adx(vals, n=14):
    if len(vals) < n + 1:
        return None
    diffs = [vals[i] - vals[i - 1] for i in range(len(vals) - n, len(vals))]
    up = sum(d for d in diffs if d > 0)
    down = -sum(d for d in diffs if d < 0)
    tr = sum(abs(d) for d in diffs)
    if tr == 0:
        return 0.0
    dip = 100 * up / tr
    dim = 100 * down / tr
    return 100 * abs(dip - dim) / (dip + dim) if dip + dim else 0.0

def in_no_trade(t: str, window: str):
    start_s, end_s = window.split("-")
    fmt = "%H:%M"
    cur = datetime.strptime(t[:5], "%H:%M").time()
    start = datetime.strptime(start_s, fmt).time()
    end = datetime.strptime(end_s, fmt).time()
    return start <= cur <= end if start <= end else (cur >= start or cur <= end)

def main():
    ap = argparse.ArgumentParser(description="Monitor gold CSV and suggest sell timing")
    ap.add_argument("--dir", default=Path(__file__).resolve().parent, type=Path)
    ap.add_argument("--grams", type=float, default=250)
    ap.add_argument("--cost", type=float, default=None, help="成本价 CNY/克")
    ap.add_argument("--t1", type=float, default=1133.48, help="止盈1 CNY/克")
    ap.add_argument("--t2", type=float, default=1142.63, help="止盈2 CNY/克")
    ap.add_argument("--stop", type=float, default=1113.62, help="止损 CNY/克")
    ap.add_argument("--no-trade", dest="no_trade", default="02:00-09:10")
    ap.add_argument("--poll", type=float, default=5, help="轮询秒数")
    args = ap.parse_args()

    sold1 = sold2 = False
    last_stamp = ""
    while True:
        path = latest_csv(args.dir)
        if not path:
            print("⚠️ 未找到 CSV 文件")
            time.sleep(args.poll)
            continue
        row = parse_last_row(path)
        if not row:
            time.sleep(args.poll)
            continue
        stamp, t, cny, usd, prices = row
        if stamp == last_stamp:
            time.sleep(args.poll)
            continue
        last_stamp = stamp
        ma5, ma12 = sma(prices, 5), sma(prices, 12)
        rsi14, atr14 = rsi(prices, 14), atr(prices, 14)
        adx14 = adx(prices, 14)
        bb = bollinger(prices, 20)
        bb_w = (bb[1] - bb[2]) / bb[0] if bb else None
        atr50 = atr(prices, 50)
        state = "中性"
        if adx14 is not None and adx14 < 25 and bb_w is not None and bb_w < 0.01:
            state = "震荡市"
        elif adx14 is not None and adx14 > 25 and ma5 and ma12:
            state = "强趋势市"
        elif atr14 is not None and atr50 is not None and atr14 > atr50 * 1.3:
            state = "波动市"
        pnl = (cny - args.cost) * args.grams if args.cost is not None else None
        pnl_s = f" | 浮盈亏: {pnl:.2f} 元" if pnl is not None else ""
        ind = f" | MA5 {ma5:.2f} MA12 {ma12:.2f} RSI14 {rsi14:.1f} ADX14 {adx14:.1f} ATR14 {atr14:.2f}"
        if bb:
            ind += f" BB({bb[2]:.2f}-{bb[1]:.2f})"
        ind += f" | 环境 {state}"
        if in_no_trade(t, args.no_trade):
            print(f"🕒 {stamp} 不可交易区间 | 现价 {cny} CNY/克{pnl_s}{ind}")
            time.sleep(args.poll)
            continue
        if cny <= args.stop:
            print(f"🛑 {stamp} 触发止损 | 建议卖出全部 | {cny} CNY/克 ({usd}){pnl_s}{ind}")
            sold1 = sold2 = True
        elif cny >= args.t2 and not sold2:
            print(f"✅ {stamp} 达到止盈2 | 建议卖出剩余 | {cny} CNY/克 ({usd}){pnl_s}{ind}")
            sold2 = True
        elif cny >= args.t1 and not sold1:
            print(f"✅ {stamp} 达到止盈1 | 建议卖出50% | {cny} CNY/克 ({usd}){pnl_s}{ind}")
            sold1 = True
        else:
            print(f"⏳ {stamp} 观望 | 现价 {cny} CNY/克 ({usd}){pnl_s}{ind}")
        time.sleep(args.poll)

if __name__ == "__main__":
    main()
