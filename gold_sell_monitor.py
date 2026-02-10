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
    time_str, usd_str, cny_str = lines[-1].split(",")
    cny = float(cny_str.split()[0])
    m = DATE_RE.search(path.name)
    date_str = m.group(1) if m else datetime.now().strftime("%Y-%m-%d")
    stamp = f"{date_str} {time_str}"
    return stamp, time_str, cny, usd_str

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
        stamp, t, cny, usd = row
        if stamp == last_stamp:
            time.sleep(args.poll)
            continue
        last_stamp = stamp
        pnl = (cny - args.cost) * args.grams if args.cost is not None else None
        pnl_s = f" | 浮盈亏: {pnl:.2f} 元" if pnl is not None else ""
        if in_no_trade(t, args.no_trade):
            print(f"🕒 {stamp} 不可交易区间 | 现价 {cny} CNY/克{pnl_s}")
            time.sleep(args.poll)
            continue
        if cny <= args.stop:
            print(f"🛑 {stamp} 触发止损 | 建议卖出全部 | {cny} CNY/克 ({usd}){pnl_s}")
            sold1 = sold2 = True
        elif cny >= args.t2 and not sold2:
            print(f"✅ {stamp} 达到止盈2 | 建议卖出剩余 | {cny} CNY/克 ({usd}){pnl_s}")
            sold2 = True
        elif cny >= args.t1 and not sold1:
            print(f"✅ {stamp} 达到止盈1 | 建议卖出50% | {cny} CNY/克 ({usd}){pnl_s}")
            sold1 = True
        else:
            print(f"⏳ {stamp} 观望 | 现价 {cny} CNY/克 ({usd}){pnl_s}")
        time.sleep(args.poll)

if __name__ == "__main__":
    main()
