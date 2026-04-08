#!/usr/bin/env python3
import argparse,csv,re,time
from datetime import datetime
from pathlib import Path
from scripts.analysis.indicators import adx,atr,bollinger,rsi,sma

DATE_RE=re.compile(r"gold_(\d{4}-\d{2}-\d{2})\.csv$")

def latest_csv(d:Path):
    fs=sorted(d.glob("gold_*.csv"))
    return fs[-1] if fs else None

def load_last(path:Path):
    with path.open(encoding="utf-8") as f:
        r=list(csv.reader(f))
    if len(r)<2:return None
    prices=[float(x[2].split()[0]) for x in r[1:] if len(x)>=3]
    t,usd,cny=r[-1]
    m=DATE_RE.search(path.name)
    ds=m.group(1) if m else datetime.now().strftime("%Y-%m-%d")
    return f"{ds} {t}",t,float(cny.split()[0]),usd,prices

def in_no_trade(t,win):
    s,e=win.split("-")
    cur=datetime.strptime(t[:5],"%H:%M").time()
    s=datetime.strptime(s,"%H:%M").time();e=datetime.strptime(e,"%H:%M").time()
    return s<=cur<=e if s<=e else (cur>=s or cur<=e)

def regime(p):
    ma5,ma20=sma(p,5),sma(p,20)
    rsi14,atr14,atr50=rsi(p,14),atr(p,14),atr(p,50)
    adx14=adx(p,14);bb=bollinger(p,20)
    bbw=(bb[1]-bb[2])/bb[0] if bb else None
    if adx14 is not None and ma5 and ma20:
        d="↑" if ma5>ma20 else "↓" if ma5<ma20 else "→"
        s="强" if adx14>=30 else "弱" if adx14<20 else "中"
        if adx14>25:return f"趋势{d}{s}",ma5,ma20,rsi14,atr14,adx14,bb
    if bbw is not None and bbw<0.01:return "震荡",ma5,ma20,rsi14,atr14,adx14,bb
    if atr14 and atr50 and atr14>atr50*1.3:return "高波动",ma5,ma20,rsi14,atr14,adx14,bb
    return "中性",ma5,ma20,rsi14,atr14,adx14,bb

def levels(p,prices,cost):
    atr14=atr(prices,14)
    base=cost or (sma(prices,20) or p)
    vol=atr14 or (abs(p-base) or 1)
    return base-3*vol,base+2*vol,base+3.5*vol,vol

def decide(p,usd,args,stats,peak,sold,prices):
    reg,ma5,ma20,rsi14,atr14,adx14,bb=stats
    pnl=(p-args.cost)*args.grams if args.cost is not None else None
    stop,tp1,tp2,vol=levels(p,prices,args.cost)
    if stop and p<=stop:return "🛑 触发止损 | 全部卖出",2,pnl
    if tp2 and sold<2 and p>=tp2:return "✅ 达到止盈2 | 卖出剩余",2,pnl
    if tp1 and sold<1 and p>=tp1:return "✅ 达到止盈1 | 卖出50%",1,pnl
    if peak and p<=peak-vol*2 and sold<2:return "🟠 回撤止盈 | 卖出剩余",2,pnl
    if reg=="趋势" and ma5 and ma20 and ma5<ma20 and rsi14 and rsi14<35 and sold<2:
        return "⚠️ 趋势走弱 | 减仓",max(sold,1),pnl
    return "⏳ 观望",sold,pnl

def main():
    ap=argparse.ArgumentParser("Monitor gold CSV and suggest sells")
    ap.add_argument("--dir",default=Path(__file__).resolve().parent,type=Path)
    ap.add_argument("--grams",type=float,default=250)
    ap.add_argument("--cost",type=float,default=None,help="成本价 CNY/克")
    ap.add_argument("--no-trade",dest="no_trade",default="02:00-09:10")
    ap.add_argument("--poll",type=float,default=5,help="轮询秒数")
    args=ap.parse_args()
    last="";sold=0;peak=None
    while True:
        path=latest_csv(args.dir)
        if not path:
            print("⚠️ 未找到 CSV 文件");time.sleep(args.poll);continue
        row=load_last(path)
        if not row:time.sleep(args.poll);continue
        stamp,t,p,usd,prices=row
        if stamp==last:time.sleep(args.poll);continue
        last=stamp;peak=max(peak or p,p)
        stats=regime(prices)
        if in_no_trade(t,args.no_trade):
            print(f"🕒 {stamp} 不可交易 | 现价 {p} CNY/克 ({usd}) | 环境 {stats[0]}")
            time.sleep(args.poll);continue
        msg,sold,pnl=decide(p,usd,args,stats,peak,sold,prices)
        pnl_s=f" | 浮盈亏 {pnl:.2f} 元" if pnl is not None else ""
        ma5,ma20,rsi14,atr14,adx14,bb=stats[1:]
        fmt=lambda v,f: f.format(v) if v is not None else "NA"
        ind=f" MA5 {fmt(ma5,'{:.2f}')} MA20 {fmt(ma20,'{:.2f}')} RSI14 {fmt(rsi14,'{:.1f}')} ADX14 {fmt(adx14,'{:.1f}')} ATR14 {fmt(atr14,'{:.2f}')}"
        if bb:ind+=f" BB({bb[2]:.2f}-{bb[1]:.2f})"
        print(f"{msg} | {p} CNY/克 ({usd}){pnl_s} | 环境 {stats[0]} |{ind}")
        time.sleep(args.poll)

if __name__=="__main__":
    main()
