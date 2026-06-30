#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
"""
黄金价格宏观因子下载器

数据源:
  - FRED (Federal Reserve Economic Data): 利率/通胀/就业/美元/VIX/SP500/WTI 等
  - 东方财富 (East Money): DJIA, NASDAQ (补充指数)

输出:
  data/macro/macro_daily.csv         # 日频合并数据
  data/macro/macro_daily.parquet     # Parquet 格式
  data/macro/individual/*.csv        # 各因子原始数据
  data/macro/metadata.json           # 因子元信息

用法:
  python scripts/download_macro_factors.py              # 下载全部
  python scripts/download_macro_factors.py --force      # 忽略缓存
  python scripts/download_macro_factors.py --start 2020-01-01 --end 2026-06-27
"""

import argparse, json, logging, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# 项目路径
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "macro"
INDIVIDUAL_DIR = DATA_DIR / "individual"

# 默认日期范围 (与 gold_prices 表对齐)
GOLD_START_DATE = "2019-12-01"
GOLD_END_DATE   = "2026-07-01"

log = logging.getLogger("macro_dl")

# ===================================================================
# 因子定义
# ===================================================================

FRED_SERIES = {
    # ---- 利率 (核心驱动) ----
    "fed_funds": {
        "series_id": "DFF",
        "name": "Federal Funds Effective Rate",
        "category": "interest_rates",
        "description": "联邦基金利率，美联储政策利率",
        "corr_sign": "negative",
        "freq": "daily",
    },
    "us5y": {
        "series_id": "DGS5",
        "name": "5-Year Treasury Constant Maturity Rate",
        "category": "interest_rates",
        "description": "5年期国债收益率",
        "corr_sign": "negative",
        "freq": "daily",
    },
    "us10y": {
        "series_id": "DGS10",
        "name": "10-Year Treasury Constant Maturity Rate",
        "category": "interest_rates",
        "description": "10年期国债收益率 (黄金定价最重要的利率指标)",
        "corr_sign": "negative",
        "freq": "daily",
    },
    "us30y": {
        "series_id": "DGS30",
        "name": "30-Year Treasury Constant Maturity Rate",
        "category": "interest_rates",
        "description": "30年期国债收益率",
        "corr_sign": "negative",
        "freq": "daily",
    },
    "tips_10y": {
        "series_id": "DFII10",
        "name": "10-Year TIPS Yield (Real Rate)",
        "category": "interest_rates",
        "description": "10年期通胀保值国债实际收益率，黄金定价最核心变量",
        "corr_sign": "negative",
        "freq": "daily",
    },

    # ---- 通胀 ----
    "cpi": {
        "series_id": "CPIAUCSL",
        "name": "CPI All Urban Consumers",
        "category": "inflation",
        "description": "消费者物价指数 (月频, 前向填充到日频)",
        "corr_sign": "positive",
        "freq": "monthly",
    },
    "core_cpi": {
        "series_id": "CPILFESL",
        "name": "Core CPI (ex Food & Energy)",
        "category": "inflation",
        "description": "核心 CPI (不含食品能源, 月频)",
        "corr_sign": "positive",
        "freq": "monthly",
    },
    "breakeven_10y": {
        "series_id": "T10YIE",
        "name": "10-Year Breakeven Inflation Rate",
        "category": "inflation",
        "description": "10年期盈亏平衡通胀率 (市场通胀预期)",
        "corr_sign": "positive",
        "freq": "daily",
    },

    # ---- 美元 ----
    "trade_usd": {
        "series_id": "DTWEXBGS",
        "name": "Trade Weighted USD Index (Broad)",
        "category": "dollar",
        "description": "贸易加权美元指数 (广义), 比 DXY 更全面",
        "corr_sign": "negative",
        "freq": "daily",
    },
    "dxy_advanced": {
        "series_id": "DTWEXAFEGS",
        "name": "USD Index: Advanced Foreign Economies",
        "category": "dollar",
        "description": "发达经济体美元指数 (最接近 DXY 的 FRED 指标)",
        "corr_sign": "negative",
        "freq": "daily",
    },

    # ---- 实体经济 ----
    "unemployment": {
        "series_id": "UNRATE",
        "name": "Unemployment Rate",
        "category": "real_economy",
        "description": "失业率 (月频, 经济健康度)",
        "corr_sign": "varies",
        "freq": "monthly",
    },
    "gdp": {
        "series_id": "GDPC1",
        "name": "Real GDP (Billions of Chained 2017 $)",
        "category": "real_economy",
        "description": "实际 GDP (季频, 经济增长)",
        "corr_sign": "varies",
        "freq": "quarterly",
    },
    "m2": {
        "series_id": "M2SL",
        "name": "M2 Money Supply (Billions)",
        "category": "real_economy",
        "description": "M2货币供应量 (月频, 流动性 proxy)",
        "corr_sign": "positive",
        "freq": "monthly",
    },

    # ---- 风险情绪 ----
    "vix": {
        "series_id": "VIXCLS",
        "name": "CBOE Volatility Index (VIX)",
        "category": "risk_sentiment",
        "description": "恐慌指数，高VIX → 避险买黄金",
        "corr_sign": "positive",
        "freq": "daily",
    },
    "sp500": {
        "series_id": "SP500",
        "name": "S&P 500 Index",
        "category": "risk_sentiment",
        "description": "标普500指数，风险偏好基准",
        "corr_sign": "varies",
        "freq": "daily",
    },

    # ---- 商品 ----
    "wti": {
        "series_id": "DCOILWTICO",
        "name": "WTI Crude Oil Spot Price",
        "category": "commodities",
        "description": "WTI 原油现货价，通胀传导 → 金价",
        "corr_sign": "positive",
        "freq": "daily",
    },
}


# 东方财富补充数据 (FRED 不覆盖的指标)
EASTMONEY_INDICES = {
    "djia": {
        "secid": "100.DJIA",
        "name": "Dow Jones Industrial Average",
        "category": "risk_sentiment",
        "description": "道琼斯工业指数",
        "corr_sign": "varies",
    },
    "nasdaq": {
        "secid": "100.NDX",
        "name": "NASDAQ 100 Index",
        "category": "risk_sentiment",
        "description": "纳斯达克100指数，科技/成长股情绪",
        "corr_sign": "varies",
    },
}


# ===================================================================
# FRED 下载
# ===================================================================

def download_fred_all(series_defs: dict, start: str, end: str,
                      force: bool = False) -> dict[str, pd.Series]:
    """通过 pandas_datareader 批量下载 FRED 数据."""
    import pandas_datareader.data as web

    INDIVIDUAL_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    n_ok, n_fail = 0, 0

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt   = datetime.strptime(end, "%Y-%m-%d")

    for i, (key, cfg) in enumerate(series_defs.items(), 1):
        sid = cfg["series_id"]
        cache_file = INDIVIDUAL_DIR / f"fred_{key}.csv"

        if cache_file.exists() and not force:
            s = pd.read_csv(cache_file, index_col=0, parse_dates=True).squeeze("columns")
            log.info(f"[{i:2d}/{len(series_defs)}] FRED {key:16s} ({sid:14s}) ← 缓存 ({len(s):5d} obs)")
            results[key] = s
            n_ok += 1
            continue

        try:
            df = web.DataReader(sid, "fred", start=start_dt, end=end_dt)
            series = df.iloc[:, 0].dropna()
            series.name = key
            series.to_csv(cache_file, header=True)
            results[key] = series
            n_ok += 1
            log.info(f"[{i:2d}/{len(series_defs)}] FRED {key:16s} ({sid:14s}) ✅ {len(series):5d} obs → {cache_file.name}")
        except Exception as e:
            log.warning(f"[{i:2d}/{len(series_defs)}] FRED {key:16s} ({sid:14s}) ❌ {e}")
            n_fail += 1

        time.sleep(0.3)  # rate limiting for FRED API

    log.info(f"  FRED 下载: {n_ok} 成功, {n_fail} 失败")
    return results


# ===================================================================
# 东方财富下载 (美股指数)
# ===================================================================

def download_eastmoney_all(indices: dict, start: str, end: str,
                           force: bool = False) -> dict[str, pd.Series]:
    """通过东方财富 API 下载美股指数 K 线."""
    INDIVIDUAL_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }

    # 转换日期格式: YYYY-MM-DD → YYYYMMDD
    beg = start.replace("-", "")
    end_ = end.replace("-", "")

    for i, (key, cfg) in enumerate(indices.items(), 1):
        cache_file = INDIVIDUAL_DIR / f"em_{key}.csv"
        secid = cfg["secid"]

        if cache_file.exists() and not force:
            s = pd.read_csv(cache_file, index_col=0, parse_dates=True).squeeze("columns")
            log.info(f"[EM {i}/{len(indices)}] {key:12s} ({secid:10s}) ← 缓存 ({len(s):5d} rows)")
            results[key] = s
            continue

        url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
               f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
               f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
               f"&klt=101&fqt=0&beg={beg}&end={end_}")

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            klines = data.get("data", {}).get("klines")
            if not klines:
                log.warning(f"[EM {i}/{len(indices)}] {key:12s} ({secid:10s}) ⚠️ 无数据")
                continue

            # 解析: date,open,close,high,low,volume,amount,amplitude,change%,change, turnover%
            dates, closes = [], []
            for line in klines:
                parts = line.split(",")
                dates.append(parts[0])
                closes.append(float(parts[2]))  # close price

            series = pd.Series(closes, index=pd.to_datetime(dates), name=key)
            series = series[~series.index.duplicated(keep="last")]
            series.to_csv(cache_file, header=True)
            results[key] = series

            log.info(f"[EM {i}/{len(indices)}] {key:12s} ({secid:10s}) ✅ {len(series):5d} rows → {cache_file.name}")

        except Exception as e:
            log.warning(f"[EM {i}/{len(indices)}] {key:12s} ({secid:10s}) ❌ {e}")

        time.sleep(0.5)

    log.info(f"  东方财富: {len(results)} 成功")
    return results


# ===================================================================
# 数据合并 & 衍生因子
# ===================================================================

def merge_all_to_daily(fred_data: dict[str, pd.Series],
                       em_data: dict[str, pd.Series],
                       start: str, end: str) -> pd.DataFrame:
    """将所有因子对齐到统一日频 B-day DataFrame."""
    full_idx = pd.bdate_range(start=start, end=end)
    df = pd.DataFrame(index=full_idx)

    # 合并 FRED 数据
    for key, series in fred_data.items():
        s = series.copy()
        s.index = pd.to_datetime(s.index).normalize()
        df[key] = s.reindex(full_idx)

    # 合并东方财富数据
    for key, series in em_data.items():
        s = series.copy()
        s.index = pd.to_datetime(s.index).normalize()
        df[key] = s.reindex(full_idx)

    # Forward fill → Back fill → 0 fill (处理低频数据: 月频/季频)
    df = df.ffill().bfill().fillna(0)

    return df


def compute_derived_factors(df: pd.DataFrame) -> pd.DataFrame:
    """计算衍生因子 (捕捉跨市场关系和价格动量)."""
    out = df.copy()
    n = 0

    # === 涨跌幅 (5日, 20日, 60日) ===
    price_cols = ["sp500", "djia", "nasdaq", "wti", "trade_usd", "dxy_advanced"]
    for col in price_cols:
        if col not in out.columns:
            continue
        for w in [5, 20, 60]:
            out[f"{col}_ret_{w}d"] = out[col].pct_change(w)
            n += 1

    # === 收益率变化 ===
    rate_cols = ["fed_funds", "us5y", "us10y", "us30y", "tips_10y", "breakeven_10y", "vix"]
    for col in rate_cols:
        if col not in out.columns:
            continue
        for w in [5, 20]:
            out[f"{col}_diff_{w}d"] = out[col].diff(w)
            n += 1

    # === 实际利率 ===
    if "us10y" in out.columns and "breakeven_10y" in out.columns:
        out["real_rate_est"] = out["us10y"] - out["breakeven_10y"]
        n += 1
    if "us5y" in out.columns and "breakeven_10y" in out.columns:
        out["real_rate_5y_est"] = out["us5y"] - out["breakeven_10y"]
        n += 1
    if "tips_10y" in out.columns:
        out["real_rate_change_5d"] = out["tips_10y"].diff(5)
        out["real_rate_change_20d"] = out["tips_10y"].diff(20)
        n += 2

    # === 收益率曲线 ===
    if "us30y" in out.columns and "us5y" in out.columns:
        out["yield_curve_5y30y"] = out["us30y"] - out["us5y"]
        n += 1
    if "us10y" in out.columns and "us5y" in out.columns:
        out["yield_curve_5y10y"] = out["us10y"] - out["us5y"]
        n += 1
    if "us30y" in out.columns and "us10y" in out.columns:
        out["yield_curve_10y30y"] = out["us30y"] - out["us10y"]
        n += 1

    # === 美元动量 ===
    for col in ["trade_usd", "dxy_advanced"]:
        if col not in out.columns:
            continue
        out[f"{col}_ma_20"] = out[col].rolling(20).mean()
        out[f"{col}_vs_ma20"] = out[col] / (out[f"{col}_ma_20"] + 1e-10) - 1
        n += 2

    # === CPI 同比 (近似) ===
    if "cpi" in out.columns:
        out["cpi_yoy_approx"] = out["cpi"].pct_change(252)  # ~1 year of trading days
        n += 1
    if "core_cpi" in out.columns:
        out["core_cpi_yoy_approx"] = out["core_cpi"].pct_change(252)
        n += 1

    # === M2 同比 ===
    if "m2" in out.columns:
        out["m2_yoy_approx"] = out["m2"].pct_change(252)
        n += 1

    # === 风险偏好综合指标 ===
    if "sp500" in out.columns and "vix" in out.columns:
        out["risk_appetite"] = out["sp500"].pct_change(20) * 100 - out["vix"].diff(20)
        n += 1

    # === 股债性价比 ===
    if "us10y" in out.columns and "sp500" in out.columns:
        out["equity_bond_spread"] = (1 / (out["sp500"].pct_change(252) + 0.01 + 1e-10)) - out["us10y"]
        n += 1

    # === 波动率 (自身) ===
    vol_cols = ["sp500", "djia", "nasdaq", "wti", "trade_usd", "dxy_advanced",
                "us10y", "us5y", "vix"]
    for col in vol_cols:
        if col not in out.columns:
            continue
        out[f"{col}_vol_20d"] = out[col].pct_change().rolling(20).std()
        n += 1

    # === 跨市场相关性 (滚动) ===
    # SP500 vs VIX (负相关增强 = 风险off)
    if "sp500" in out.columns and "vix" in out.columns:
        sp_ret = out["sp500"].pct_change()
        vix_diff = out["vix"].diff()
        out["sp500_vix_corr_20d"] = sp_ret.rolling(20).corr(vix_diff)
        n += 1

    # 美元 vs 黄金 proxy (美元强 → 金价弱)
    if "trade_usd" in out.columns and "sp500" in out.columns:
        usd_ret = out["trade_usd"].pct_change()
        sp_ret = out["sp500"].pct_change()
        out["usd_sp500_corr_20d"] = usd_ret.rolling(20).corr(sp_ret)
        n += 1

    log.info(f"  🧬 +{n} 个衍生因子, 总列数: {len(out.columns)}")
    return out


# ===================================================================
# 输出
# ===================================================================

def print_summary(df: pd.DataFrame):
    """打印因子统计摘要."""
    print("\n" + "=" * 80)
    print("📊 宏观因子统计摘要")
    print("=" * 80)
    print(f"  日期范围: {df.index[0].date()} ~ {df.index[-1].date()}")
    print(f"  交易日数: {len(df):,}")
    print(f"  因子总数: {len(df.columns)}")

    # 按类别分组
    raw_fred = [c for c in FRED_SERIES if c in df.columns]
    raw_em   = [c for c in EASTMONEY_INDICES if c in df.columns]
    derived  = [c for c in df.columns if c not in FRED_SERIES and c not in EASTMONEY_INDICES]

    print(f"  FRED 原始: {len(raw_fred)} | 东方财富: {len(raw_em)} | 衍生: {len(derived)}")

    print(f"\n  📥 FRED 原始因子 ({len(raw_fred)}):")
    for key in raw_fred:
        s = df[key]; s2 = s[s != 0]
        print(f"     {key:<24s} mean={s2.mean():>14.4f}  std={s2.std():>14.4f}  "
              f"non-zero={len(s2):>5d}/{len(s)}")

    if raw_em:
        print(f"\n  📥 东方财富因子 ({len(raw_em)}):")
        for key in raw_em:
            s = df[key]
            print(f"     {key:<24s} mean={s.mean():>14.2f}  std={s.std():>14.2f}")

    print(f"\n  🧬 衍生因子 ({len(derived)}):")
    for key in sorted(derived):
        s = df[key]
        print(f"     {key:<35s} mean={s.mean():>12.6f}  std={s.std():>12.6f}")


def save_output(df: pd.DataFrame):
    """保存数据和元信息."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # CSV
    csv_path = DATA_DIR / "macro_daily.csv"
    df.to_csv(csv_path, float_format="%.6f")
    log.info(f"  💾 CSV:  {csv_path} ({csv_path.stat().st_size / 1024:.0f} KB)")

    # Parquet
    pq_path = DATA_DIR / "macro_daily.parquet"
    df.to_parquet(pq_path)
    log.info(f"  💾 Parquet: {pq_path} ({pq_path.stat().st_size / 1024:.0f} KB)")

    # Metadata
    meta = {
        "generated_at": datetime.now().isoformat(),
        "date_range": [str(df.index[0].date()), str(df.index[-1].date())],
        "num_trading_days": len(df),
        "total_factors": len(df.columns),
        "sources": {"fred": len([c for c in FRED_SERIES if c in df.columns]),
                    "eastmoney": len([c for c in EASTMONEY_INDICES if c in df.columns]),
                    "derived": len([c for c in df.columns
                                   if c not in FRED_SERIES and c not in EASTMONEY_INDICES])},
        "factors": {},
    }

    for cfg_dict, source in [(FRED_SERIES, "FRED"), (EASTMONEY_INDICES, "EastMoney")]:
        for key, cfg in cfg_dict.items():
            present = key in df.columns
            meta["factors"][key] = {
                "source": source,
                "name": cfg["name"],
                "category": cfg["category"],
                "corr_sign": cfg["corr_sign"],
                "description": cfg["description"],
                "quality": "ok" if present else "missing",
            }

    for col in sorted(df.columns):
        if col not in FRED_SERIES and col not in EASTMONEY_INDICES:
            meta["factors"][col] = {
                "source": "derived",
                "name": col, "category": "derived",
                "corr_sign": "varies",
                "description": "衍生因子",
                "quality": "ok",
            }

    meta_path = DATA_DIR / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    log.info(f"  📝 元信息: {meta_path}")


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description="下载黄金价格宏观影响因子 (FRED + 东方财富)")
    parser.add_argument("--start", type=str, default=GOLD_START_DATE,
                        help=f"开始日期 (默认: {GOLD_START_DATE})")
    parser.add_argument("--end", type=str, default=GOLD_END_DATE,
                        help=f"结束日期 (默认: {GOLD_END_DATE})")
    parser.add_argument("--force", action="store_true",
                        help="强制重新下载，忽略缓存")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    print("=" * 80)
    print("🔽 黄金价格宏观影响因子下载器 (FRED + 东方财富)")
    print(f"   日期范围: {args.start} ~ {args.end}")
    print(f"   FRED 系列: {len(FRED_SERIES)} 个")
    print(f"   东方财富:  {len(EASTMONEY_INDICES)} 个")
    print(f"   输出目录:  {DATA_DIR}")
    print("=" * 80)
    print()

    # -- 1. 下载 FRED --
    print("📥 [1/3] 下载 FRED 经济数据...")
    fred_data = download_fred_all(FRED_SERIES, args.start, args.end, force=args.force)

    # -- 2. 下载东方财富 --
    print("\n📥 [2/3] 下载东方财富指数数据...")
    em_data = download_eastmoney_all(EASTMONEY_INDICES, args.start, args.end, force=args.force)

    total_raw = len(fred_data) + len(em_data)
    if total_raw == 0:
        log.error("❌ 没有任何原始因子下载成功!")
        return

    # -- 3. 合并 & 衍生 & 保存 --
    print("\n🔄 [3/3] 对齐日频 & 计算衍生因子...")
    df_daily = merge_all_to_daily(fred_data, em_data, args.start, args.end)
    df_full = compute_derived_factors(df_daily)

    save_output(df_full)
    print_summary(df_full)

    print("\n" + "=" * 80)
    print("✅ 下载完成!")
    print(f"   数据目录: {DATA_DIR}")
    print(f"   原始因子: {total_raw} 个")
    print(f"   总因子数: {len(df_full.columns)} 个")
    print(f"   下一步:   修改 data_engine.py 集成这些因子到特征工程")
    print("=" * 80)


if __name__ == "__main__":
    main()
