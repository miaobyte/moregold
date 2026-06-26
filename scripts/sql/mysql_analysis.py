#!/usr/bin/env python3
"""
MySQL 金价分析脚本

功能:
  1. 各星期几均价统计
  2. 各星期几波动率
  3. 日内按小时走势（分星期几）
  4. 各星期几涨跌概率
  5. 隔夜跳空统计
  6. 周度收益率分布
  7. 综合交易建议
  8. 自定义交易策略收益计算 (SQL 驱动, 极快)

前提: 已运行 import_to_mysql.py 导入数据

用法:
    python3 scripts/sql/mysql_analysis.py [--demo] [--plot]
"""

import os
import sys
import argparse
import mysql.connector
from datetime import datetime
from collections import defaultdict

# ============================================================
# 配置
# ============================================================

DB_CONFIG = {
    "host": "bj-cdb-9ermqj8g.sql.tencentcdb.com",
    "port": 26092,
    "user": "gold_ro",
    "password": "BNbQMsn4hhnmuw6P",
    "database": "gold",
    "charset": "utf8mb4",
}

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def get_connection():
    conn = mysql.connector.connect(**DB_CONFIG)
    # 增大 GROUP_CONCAT 限制，避免日内数据被截断
    cur = conn.cursor()
    cur.execute("SET SESSION group_concat_max_len = 1000000")
    cur.close()
    return conn


def fetchall(cursor, sql, params=None):
    cursor.execute(sql, params or ())
    return cursor.fetchall()


def fetchone(cursor, sql, params=None):
    cursor.execute(sql, params or ())
    return cursor.fetchone()


# ============================================================
# 0. 基本信息
# ============================================================

def show_info(cursor):
    row = fetchone(cursor, """
        SELECT COUNT(*), MIN(trade_date), MAX(trade_date),
               DATEDIFF(MAX(trade_date), MIN(trade_date))
        FROM gold_prices
    """)
    print(f"✅ MySQL 数据: {row[0]} 条, {row[1]} ~ {row[2]}, 跨度 {row[3]} 天")


# ============================================================
# 1. 各星期几均价
# ============================================================

def analyze_avg_by_weekday(cursor):
    print()
    print("=" * 70)
    print("📊 一、各星期几价格统计")
    print("=" * 70)

    rows = fetchall(cursor, """
        SELECT
            weekday,
            COUNT(*)                     AS n,
            ROUND(AVG(price_usd), 2)     AS avg_p,
            ROUND(MAX(price_usd), 2)     AS max_p,
            ROUND(MIN(price_usd), 2)     AS min_p,
            ROUND(STDDEV_SAMP(price_usd), 2) AS std_p
        FROM gold_prices
        WHERE weekday < 5
        GROUP BY weekday ORDER BY weekday
    """)

    # 中位数需要单独计算
    print(f"  {'星期':<6} {'记录数':>7} {'均价(USD)':>12} {'最高(USD)':>12} {'最低(USD)':>12} {'波动率':>12}")
    print("  " + "-" * 65)

    for wd, n, avg, mx, mn, std in rows:
        print(f"  {WEEKDAY_NAMES[wd]:<6} {n:>7} {avg:>12,.2f} {mx:>12,.2f} {mn:>12,.2f} {std:>12,.2f}")

    cheapest = min(rows, key=lambda r: r[2])
    dearest  = max(rows, key=lambda r: r[2])
    print(f"\n  💰 均价最便宜: {WEEKDAY_NAMES[cheapest[0]]} ({cheapest[2]:,.2f})")
    print(f"  💸 均价最贵:   {WEEKDAY_NAMES[dearest[0]]} ({dearest[2]:,.2f})")


# ============================================================
# 2. 各星期几日内振幅
# ============================================================

def analyze_volatility_by_weekday(cursor):
    print()
    print("=" * 70)
    print("📈 二、各星期几日振幅（日内波动幅度）")
    print("=" * 70)

    rows = fetchall(cursor, """
        SELECT
            weekday,
            COUNT(DISTINCT trade_date)   AS n_days,
            ROUND(AVG((day_high - day_low) / NULLIF(day_open, 0)), 6) AS avg_amp,
            ROUND(MAX((day_high - day_low) / NULLIF(day_open, 0)), 6) AS max_amp,
            ROUND(MIN((day_high - day_low) / NULLIF(day_open, 0)), 6) AS min_amp
        FROM (
            SELECT
                trade_date,
                weekday,
                MIN(price_usd) AS day_low,
                MAX(price_usd) AS day_high,
                SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1) AS day_open
            FROM gold_prices
            WHERE weekday < 5
            GROUP BY trade_date, weekday
        ) t
        WHERE day_open > 0
        GROUP BY weekday ORDER BY weekday
    """)

    print(f"  {'星期':<6} {'交易日数':>8} {'平均日振幅':>12} {'最大日振幅':>12} {'最小日振幅':>12}")
    print("  " + "-" * 55)

    for wd, n, avg, mx, mn in rows:
        print(f"  {WEEKDAY_NAMES[wd]:<6} {n:>8} {avg*100:>+11.2f}% {mx*100:>+11.2f}% {mn*100:>+11.2f}%")

    if rows:
        most = max(rows, key=lambda r: r[2])
        print(f"\n  ⚡ 波动最大: {WEEKDAY_NAMES[most[0]]} (平均 {most[2]*100:+.2f}%)")


# ============================================================
# 3. 日内按小时走势
# ============================================================

def analyze_intraday_by_weekday(cursor):
    print()
    print("=" * 70)
    print("🕐 三、各星期几分时段走势（按小时）")
    print("=" * 70)

    # 使用 CTE 替代临时表（腾讯云 MySQL 禁用 TEMPORARY TABLE）
    for wd in range(5):
        rows = fetchall(cursor, """
            WITH daily_open AS (
                SELECT trade_date, weekday,
                       SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1) AS open_price
                FROM gold_prices
                WHERE weekday < 5
                GROUP BY trade_date, weekday
            )
            SELECT
                g.hour,
                ROUND(AVG(g.price_usd), 2)   AS hour_avg,
                COUNT(*)                      AS n,
                ROUND(AVG((g.price_usd - d.open_price) / NULLIF(d.open_price, 0)), 6) AS rel
            FROM gold_prices g
            JOIN daily_open d ON g.trade_date = d.trade_date
            WHERE g.weekday = %s AND d.open_price > 0
            GROUP BY g.hour
            ORDER BY g.hour
        """, [wd])

        if not rows:
            continue

        print(f"\n  {WEEKDAY_NAMES[wd]}:")
        print(f"    {'小时':<6} {'均价(USD)':>12} {'记录数':>7} {'相对开盘':>10}")
        print("    " + "-" * 40)

        prev = None
        for hour, avg, n, rel in rows:
            arrow = ""
            if prev is not None:
                arrow = "  ↑" if avg > prev else ("  ↓" if avg < prev else "  →")
            else:
                arrow = "  ●"
            prev = avg
            print(f"    {hour:02d}:00  {avg:>12,.2f} {n:>7} {rel*100:>+9.2f}%{arrow}")


# ============================================================
# 4. 各星期几涨跌概率
# ============================================================

def analyze_daily_change(cursor):
    print()
    print("=" * 70)
    print("📉 四、各星期几涨跌统计")
    print("=" * 70)

    rows = fetchall(cursor, """
        SELECT
            weekday,
            COUNT(*)            AS n,
            SUM(is_up)          AS up_days,
            SUM(is_down)        AS down_days,
            ROUND(AVG(day_change), 6)   AS avg_change,
            ROUND(AVG(CASE WHEN is_up   = 1 THEN day_change END), 6) AS avg_up,
            ROUND(AVG(CASE WHEN is_down = 1 THEN day_change END), 6) AS avg_down
        FROM (
            SELECT
                trade_date,
                weekday,
                SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1)    AS day_open,
                SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt DESC), ',', 1) AS day_close,
                (SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt DESC), ',', 1) -
                 SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1))
                / NULLIF(SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1), 0) AS day_change,
                CASE WHEN SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt DESC), ',', 1) >
                          SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1)
                     THEN 1 ELSE 0 END AS is_up,
                CASE WHEN SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt DESC), ',', 1) <
                          SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1)
                     THEN 1 ELSE 0 END AS is_down
            FROM gold_prices
            WHERE weekday < 5
            GROUP BY trade_date, weekday
        ) t
        WHERE day_open > 0
        GROUP BY weekday ORDER BY weekday
    """)

    print(f"  {'星期':<6} {'天数':>6} {'上涨':>6} {'下跌':>6} {'上涨概率':>10} {'平均涨跌':>12} {'平均涨幅':>10} {'平均跌幅':>10}")
    print("  " + "-" * 72)

    for wd, n, up, down, avg_c, avg_up, avg_down in rows:
        up_prob = up / n if n else 0
        print(f"  {WEEKDAY_NAMES[wd]:<6} {n:>6} {up:>6} {down:>6} {up_prob:>9.0%} "
              f"{avg_c*100:>+11.2f}% {(avg_up or 0)*100:>+9.2f}% {(avg_down or 0)*100:>+9.2f}%")

    if rows:
        best_buy = max(rows, key=lambda r: r[3] / r[1] if r[1] else 0)
        best_sell = max(rows, key=lambda r: r[2] / r[1] if r[1] else 0)
        print(f"\n  📌 最可能下跌（适合买入）: {WEEKDAY_NAMES[best_buy[0]]}")
        print(f"  📌 最可能上涨（适合卖出）: {WEEKDAY_NAMES[best_sell[0]]}")


# ============================================================
# 5. 隔夜跳空
# ============================================================

def analyze_overnight_gap(cursor):
    print()
    print("=" * 70)
    print("🌙 五、隔夜跳空统计")
    print("=" * 70)

    rows = fetchall(cursor, """
        WITH daily AS (
            SELECT
                trade_date,
                weekday,
                SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1)   AS day_open,
                SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt DESC), ',', 1) AS day_close
            FROM gold_prices WHERE weekday < 5
            GROUP BY trade_date, weekday
        ),
        gaps AS (
            SELECT
                d1.weekday AS from_wd,
                d2.weekday AS to_wd,
                (d2.day_open - d1.day_close) / NULLIF(d1.day_close, 0) AS gap
            FROM daily d1
            JOIN daily d2 ON d2.trade_date > d1.trade_date
                AND NOT EXISTS (
                    SELECT 1 FROM daily d3
                    WHERE d3.trade_date > d1.trade_date
                      AND d3.trade_date < d2.trade_date
                )
            WHERE d1.day_close > 0 AND d2.day_open > 0
        )
        SELECT
            from_wd, to_wd,
            COUNT(*)        AS n,
            ROUND(AVG(gap), 6) AS avg_gap,
            ROUND(MAX(gap), 6) AS max_gap,
            ROUND(MIN(gap), 6) AS min_gap
        FROM gaps
        GROUP BY from_wd, to_wd
        ORDER BY from_wd, to_wd
    """)

    print(f"  {'前日':<6} → {'次日':<6} {'次数':>6} {'平均跳空':>12} {'最大':>12} {'最小':>12}")
    print("  " + "-" * 60)
    for fw, tw, n, avg, mx, mn in rows:
        print(f"  {WEEKDAY_NAMES[fw]:<6} → {WEEKDAY_NAMES[tw]:<6} {n:>6} "
              f"{avg*100:>+11.2f}% {mx*100:>+11.2f}% {mn*100:>+11.2f}%")


# ============================================================
# 6. 周度收益率
# ============================================================

def analyze_weekly_trend(cursor):
    print()
    print("=" * 70)
    print("📅 六、周度收益率分布")
    print("=" * 70)

    row = fetchone(cursor, """
        WITH week_stats AS (
            SELECT
                year_week,
                SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1)   AS w_open,
                SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt DESC), ',', 1) AS w_close,
                COUNT(*) AS cnt
            FROM gold_prices
            GROUP BY year_week
            HAVING cnt >= 2
        ),
        week_rets AS (
            SELECT
                (w_close - w_open) / NULLIF(w_open, 0) AS ret
            FROM week_stats WHERE w_open > 0
        )
        SELECT
            COUNT(*),
            SUM(CASE WHEN ret > 0 THEN 1 ELSE 0 END),
            SUM(CASE WHEN ret < 0 THEN 1 ELSE 0 END),
            ROUND(AVG(ret) * 100, 4),
            ROUND(MAX(ret) * 100, 4),
            ROUND(MIN(ret) * 100, 4)
        FROM week_rets
    """)
    if row:
        t, up, down, avg, mx, mn = row
        print(f"  总周数: {t}")
        print(f"  上涨周: {up} ({up/t:.0%})" if t else "")
        print(f"  下跌周: {down} ({down/t:.0%})" if t else "")
        print(f"  平均周收益率: {avg:+.2f}%")
        print(f"  最大周涨幅:   {mx:+.2f}%")
        print(f"  最大周跌幅:   {mn:+.2f}%")


# ============================================================
# 7. 交易策略评估（SQL 驱动，核心优化）
# ============================================================

def evaluate_trade_schedule(cursor, schedule, min_weeks_ratio=0.4):
    """
    纯 SQL 评估交易策略，极快。

    策略: 先用临时表预计算每周每个 (weekday, hour) 上最接近目标分钟的价格，
          然后一次性 JOIN 计算所有周的收益。
    """
    N = len(schedule)

    # 获取总周数
    n_weeks = fetchone(cursor, "SELECT COUNT(DISTINCT year_week) FROM gold_prices")[0]

    # 构建 CTE 替代临时表：用 UNION ALL 组合每笔交易的买卖价
    union_parts = []
    params = []
    for ti, (bw, bh, bm, sw, sh, sm) in enumerate(schedule):
        union_parts.append("""
            SELECT %s AS trade_idx, year_week,
                   buy_price, buy_dt, sell_price, sell_dt
            FROM (
                SELECT b.year_week, b.price_usd AS buy_price, b.dt AS buy_dt,
                       s.price_usd AS sell_price, s.dt AS sell_dt
                FROM (
                    SELECT year_week, price_usd, dt,
                           ROW_NUMBER() OVER (
                               PARTITION BY year_week
                               ORDER BY ABS(minute - %s), ABS(SECOND(dt))
                           ) AS rn
                    FROM gold_prices
                    WHERE weekday = %s AND hour = %s
                ) b
                JOIN (
                    SELECT year_week, price_usd, dt,
                           ROW_NUMBER() OVER (
                               PARTITION BY year_week
                               ORDER BY ABS(minute - %s), ABS(SECOND(dt))
                           ) AS rn
                    FROM gold_prices
                    WHERE weekday = %s AND hour = %s
                ) s ON b.year_week = s.year_week AND b.rn = 1 AND s.rn = 1
            ) t
        """)
        params.extend([ti, bm, bw, bh, sm, sw, sh])

    cte_sql = "WITH trade_prices AS (" + " UNION ALL ".join(union_parts) + ")"

    # 统计
    row = fetchone(cursor, cte_sql + """
        SELECT
            COUNT(DISTINCT year_week)                        AS n,
            ROUND(AVG(total_return), 6)                     AS avg_ret,
            SUM(CASE WHEN total_return > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS win_rate,
            ROUND(MAX(total_return), 6)                     AS max_ret,
            ROUND(MIN(total_return), 6)                     AS min_ret,
            ROUND(STDDEV_SAMP(total_return), 6)              AS std_ret
        FROM (
            SELECT
                year_week,
                SUM((sell_price - buy_price) / NULLIF(buy_price, 0)) AS total_return,
                COUNT(*) AS n_trades
            FROM trade_prices
            WHERE buy_price > 0 AND sell_price > 0 AND buy_dt < sell_dt
            GROUP BY year_week
            HAVING n_trades = %s
        ) wr
    """, params + [N])

    min_weeks = max(3, n_weeks * min_weeks_ratio)
    if row is None or row[0] < min_weeks:
        return None

    n, avg_ret, win_rate, max_ret, min_ret, std_ret = row

    # 每周明细 — 复用 CTE
    week_details = fetchall(cursor, cte_sql + """
        SELECT year_week, SUM((sell_price - buy_price) / NULLIF(buy_price, 0)) AS total_return
        FROM trade_prices
        WHERE buy_price > 0 AND sell_price > 0 AND buy_dt < sell_dt
        GROUP BY year_week
        HAVING COUNT(*) = %s
        ORDER BY year_week DESC LIMIT 10
    """, params + [N])

    # 每笔统计 — 复用 CTE
    per_trade = []
    for ti in range(N):
        tr = fetchone(cursor, cte_sql + """
            SELECT
                ROUND(AVG((sell_price - buy_price) / NULLIF(buy_price, 0)), 6),
                SUM(CASE WHEN sell_price > buy_price THEN 1 ELSE 0 END)*1.0/COUNT(*),
                COUNT(*)
            FROM trade_prices
            WHERE trade_idx = %s
              AND buy_price > 0 AND sell_price > 0 AND buy_dt < sell_dt
        """, params + [ti])
        if tr:
            bw, bh, bm, sw, sh, sm = schedule[ti]
            per_trade.append({
                "buy": f"{WEEKDAY_NAMES[bw]} {bh:02d}:{bm:02d}",
                "sell": f"{WEEKDAY_NAMES[sw]} {sh:02d}:{sm:02d}",
                "avg_return": tr[0] or 0,
                "win_rate": tr[1] or 0,
                "n_trades": tr[2] or 0,
            })

    return {
        "avg_return": avg_ret,
        "n_weeks": n,
        "total_weeks": n_weeks,
        "win_rate": win_rate,
        "max_r": max_ret,
        "min_r": min_ret,
        "std_r": std_ret or 0,
        "schedule": schedule,
        "week_details": week_details,
        "per_trade_summary": per_trade,
    }


def print_trade_result(result):
    if result is None:
        print("  ❌ 有效交易周数不足")
        return

    print(f"\n  📈 总体统计:")
    print(f"     覆盖周数: {result['n_weeks']} / {result['total_weeks']} 周")
    print(f"     周均总收益: {result['avg_return']*100:+.2f}%")
    print(f"     胜率: {result['win_rate']:.0%}")
    print(f"     最大周收益: {result['max_r']*100:+.2f}%")
    print(f"     最小周收益: {result['min_r']*100:+.2f}%")
    print(f"     标准差: {result['std_r']*100:.2f}%")

    print(f"\n  🔍 每笔交易统计:")
    for i, ts in enumerate(result["per_trade_summary"]):
        print(f"     交易{i+1} ({ts['buy']} → {ts['sell']}):")
        print(f"         均值: {ts['avg_return']*100:+.2f}%, "
              f"胜率: {ts['win_rate']:.0%}, 笔数: {ts['n_trades']}")

    print(f"\n  📋 最近 {min(10, len(result['week_details']))} 周收益:")
    hdr = f"     {'周':<10}"
    for i in range(len(result["schedule"])):
        hdr += f" {'T'+str(i+1):>8}"
    hdr += f" {'合计':>8}"
    print(hdr)
    print("     " + "-" * (10 + 9 * len(result["schedule"]) + 8))
    for yw, total in result["week_details"]:
        print(f"     {yw:<10} {total*100:>+7.2f}%")


# ============================================================
# 8. 策略搜索与排名
# ============================================================

ALL_HOURS = list(range(10, 24)) + [0, 1]


def enumerate_single_trades(cursor):
    """枚举所有单笔交易策略并评估（单次 CTE 批量查询）。"""
    print(f"  📊 批量评估单笔交易策略...")

    # 使用单次 CTE 查询评估所有 (weekday, hour) 组合
    # 买入分钟固定 10，卖出分钟固定 50
    rows = fetchall(cursor, """
        WITH buy_prices AS (
            SELECT year_week, weekday AS buy_wd, hour AS buy_h,
                   price_usd AS buy_price, dt AS buy_dt,
                   ROW_NUMBER() OVER (
                       PARTITION BY year_week, weekday, hour
                       ORDER BY ABS(minute - 10), ABS(SECOND(dt))
                   ) AS rn
            FROM gold_prices WHERE weekday < 5
        ),
        sell_prices AS (
            SELECT year_week, weekday AS sell_wd, hour AS sell_h,
                   price_usd AS sell_price, dt AS sell_dt,
                   ROW_NUMBER() OVER (
                       PARTITION BY year_week, weekday, hour
                       ORDER BY ABS(minute - 50), ABS(SECOND(dt))
                   ) AS rn
            FROM gold_prices WHERE weekday < 5
        )
        SELECT b.buy_wd, b.buy_h, s.sell_wd, s.sell_h,
               COUNT(*) AS n_weeks,
               ROUND(AVG((s.sell_price - b.buy_price) / NULLIF(b.buy_price, 0)), 6) AS avg_return,
               ROUND(SUM(CASE WHEN s.sell_price > b.buy_price THEN 1 ELSE 0 END) / COUNT(*), 6) AS win_rate,
               ROUND(MAX((s.sell_price - b.buy_price) / NULLIF(b.buy_price, 0)), 6) AS max_r,
               ROUND(MIN((s.sell_price - b.buy_price) / NULLIF(b.buy_price, 0)), 6) AS min_r,
               ROUND(STDDEV_SAMP((s.sell_price - b.buy_price) / NULLIF(b.buy_price, 0)), 6) AS std_r
        FROM buy_prices b
        JOIN sell_prices s ON b.year_week = s.year_week
        WHERE b.rn = 1 AND s.rn = 1 AND b.buy_dt < s.sell_dt
        GROUP BY b.buy_wd, b.buy_h, s.sell_wd, s.sell_h
        HAVING n_weeks >= 10
    """)

    results = []
    for buy_wd, buy_h, sell_wd, sell_h, n_weeks, avg_ret, win_rate, max_r, min_r, std_r in rows:
        bo = buy_wd * 2400 + buy_h * 60 + 10
        so = sell_wd * 2400 + sell_h * 60 + 50
        if bo >= so:
            continue
        results.append({
            "buy": f"{WEEKDAY_NAMES[buy_wd]} {buy_h:02d}:10",
            "sell": f"{WEEKDAY_NAMES[sell_wd]} {sell_h:02d}:50",
            "bw": buy_wd, "bh": buy_h, "sw": sell_wd, "sh": sell_h,
            "buy_order": bo, "sell_order": so,
            "avg_return": avg_ret,
            "win_rate": win_rate,
            "n_weeks": n_weeks,
            "max_r": max_r,
            "min_r": min_r,
            "std_r": std_r or 0,
            "schedule": [(buy_wd, buy_h, 10, sell_wd, sell_h, 50)],
            "result": {
                "avg_return": avg_ret, "n_weeks": n_weeks,
                "win_rate": win_rate, "max_r": max_r,
                "min_r": min_r, "std_r": std_r or 0,
            },
        })

    results.sort(key=lambda x: -x["avg_return"])
    print(f"  有效单笔策略: {len(results)} 个 (批量CTE)")
    return results
def evaluate_pairs_batch(cursor, single_results, top_k=50):
    """批量 CTE 评估两笔交易组合 —— 替代逐对循环。"""
    candidates = single_results[:top_k]
    print(f"  📊 批量评估 2 笔组合 (Top {top_k} 单笔)...")

    if len(candidates) < 2:
        return []

    # 构建 (sell1 < buy2) 组合的过滤条件
    pair_conds = []
    for i, a in enumerate(candidates):
        for j, b in enumerate(candidates):
            if i == j:
                continue
            if a["sell_order"] < b["buy_order"]:
                # 条件: sr1.buy_wd=a.bw AND sr1.buy_h=a.bh AND sr1.sell_wd=a.sw AND sr1.sell_h=a.sh
                #   AND sr2.buy_wd=b.bw AND sr2.buy_h=b.bh AND sr2.sell_wd=b.sw AND sr2.sell_h=b.sh
                pair_conds.append(
                    f"(p1.buy_wd={a['bw']} AND p1.buy_h={a['bh']} AND p1.sell_wd={a['sw']} AND p1.sell_h={a['sh']} AND "
                    f" p2.buy_wd={b['bw']} AND p2.buy_h={b['bh']} AND p2.sell_wd={b['sw']} AND p2.sell_h={b['sh']})"
                )

    if not pair_conds:
        print("  无有效 2 笔组合")
        return []

    print(f"  有效 2 笔组合: {len(pair_conds)} 个，批量评估中...")

    where_clause = " OR ".join(pair_conds)

    sql = f"""
    WITH single_returns AS (
        SELECT b.year_week,
               b.weekday AS buy_wd, b.hour AS buy_h,
               s.weekday AS sell_wd, s.hour AS sell_h,
               (s.price_usd - b.price_usd) / NULLIF(b.price_usd, 0) AS ret
        FROM (
            SELECT year_week, weekday, hour, price_usd, dt,
                   ROW_NUMBER() OVER (
                       PARTITION BY year_week, weekday, hour
                       ORDER BY ABS(minute - 10), ABS(SECOND(dt))
                   ) AS rn
            FROM gold_prices WHERE weekday < 5
        ) b
        JOIN (
            SELECT year_week, weekday, hour, price_usd, dt,
                   ROW_NUMBER() OVER (
                       PARTITION BY year_week, weekday, hour
                       ORDER BY ABS(minute - 50), ABS(SECOND(dt))
                   ) AS rn
            FROM gold_prices WHERE weekday < 5
        ) s ON b.year_week = s.year_week
        WHERE b.rn = 1 AND s.rn = 1
          AND (b.weekday * 2400 + b.hour * 60 + 10) < (s.weekday * 2400 + s.hour * 60 + 50)
    )
    SELECT p1.buy_wd, p1.buy_h, p1.sell_wd, p1.sell_h,
           p2.buy_wd, p2.buy_h, p2.sell_wd, p2.sell_h,
           COUNT(*) AS n_weeks,
           ROUND(AVG(p1.ret + p2.ret), 6) AS avg_return,
           ROUND(SUM(CASE WHEN p1.ret + p2.ret > 0 THEN 1 ELSE 0 END) / COUNT(*), 6) AS win_rate,
           ROUND(MAX(p1.ret + p2.ret), 6) AS max_r,
           ROUND(MIN(p1.ret + p2.ret), 6) AS min_r,
           ROUND(STDDEV_SAMP(p1.ret + p2.ret), 6) AS std_r
    FROM single_returns p1
    JOIN single_returns p2 ON p1.year_week = p2.year_week
    WHERE ({where_clause})
    GROUP BY p1.buy_wd, p1.buy_h, p1.sell_wd, p1.sell_h,
             p2.buy_wd, p2.buy_h, p2.sell_wd, p2.sell_h
    HAVING n_weeks >= 8
    ORDER BY avg_return DESC
    LIMIT 50
    """

    rows = fetchall(cursor, sql)

    results = []
    for bw1, bh1, sw1, sh1, bw2, bh2, sw2, sh2, n_w, avg_r, wr, mx, mn, std in rows:
        results.append({
            "buy1": f"{WEEKDAY_NAMES[bw1]} {bh1:02d}:10",
            "sell1": f"{WEEKDAY_NAMES[sw1]} {sh1:02d}:50",
            "buy2": f"{WEEKDAY_NAMES[bw2]} {bh2:02d}:10",
            "sell2": f"{WEEKDAY_NAMES[sw2]} {sh2:02d}:50",
            "avg_return": avg_r, "win_rate": wr, "n_weeks": n_w,
            "max_r": mx, "min_r": mn, "std_r": std or 0,
        })

    print(f"  有效 2 笔策略: {len(results)} 个 (批量CTE)")
    return results


def print_rank_table(results, n_trades, top_n=20):
    """打印排名表格。"""
    label = "单笔" if n_trades == 1 else "两笔"
    print(f"\n  📊 每周 {n_trades} 次交易 — Top {min(top_n, len(results))}")
    if n_trades == 1:
        print(f"  {'排名':<4} {'买入':<13} {'卖出':<13} {'周均':>8} {'胜率':>6} {'周数':>4} {'最大':>8} {'最小':>8} {'std':>8}")
        print("  " + "-" * 76)
        for i, r in enumerate(results[:top_n]):
            print(f"  {i+1:<4} {r['buy']:<13} {r['sell']:<13} "
                  f"{r['avg_return']*100:>+7.2f}% {r['win_rate']:>5.0%} "
                  f"{r['n_weeks']:>4} {r['max_r']*100:>+7.2f}% {r['min_r']*100:>+7.2f}% "
                  f"{r['std_r']*100:>7.2f}%")
    else:
        print(f"  {'排名':<4} {'买入1':<13} {'卖出1':<13} {'买入2':<13} {'卖出2':<13} "
              f"{'周均':>8} {'胜率':>6} {'周数':>4} {'最大':>8} {'最小':>8} {'std':>8}")
        print("  " + "-" * 108)
        for i, r in enumerate(results[:top_n]):
            print(f"  {i+1:<4} {r['buy1']:<13} {r['sell1']:<13} "
                  f"{r['buy2']:<13} {r['sell2']:<13} "
                  f"{r['avg_return']*100:>+7.2f}% {r['win_rate']:>5.0%} "
                  f"{r['n_weeks']:>4} {r['max_r']*100:>+7.2f}% {r['min_r']*100:>+7.2f}% "
                  f"{r['std_r']*100:>7.2f}%")


def rank_strategies(cursor):
    """完整的策略排名: 每周 1 次和每周 2 次交易。"""
    print()
    print("=" * 70)
    print("🔍 七、策略排名（每周 1 次 & 2 次交易）")
    print("=" * 70)

    # ---- 阶段 1: 单笔交易枚举 ----
    single_results = enumerate_single_trades(cursor)
    print_rank_table(single_results, 1, top_n=20)

    # ---- 阶段 2: 两笔交易组合（批量 CTE）----
    print(f"\n  {'=' * 60}")
    print(f"  🔗 阶段 2: 从 Top 200 单笔策略批量评估 2 笔交易...")
    print(f"  {'=' * 60}")

    pair_results = evaluate_pairs_batch(cursor, single_results, top_k=50)
    print_rank_table(pair_results, 2, top_n=20)

    # ---- 阶段 3: 对比与最优详情 ----
    print(f"\n  {'=' * 60}")
    print(f"  📈 对比总结")
    print(f"  {'=' * 60}")

    if single_results:
        best1 = single_results[0]
        print(f"\n  1 笔最优: {best1['buy']} → {best1['sell']}")
        print(f"     周均 {best1['avg_return']*100:+.2f}%, 胜率 {best1['win_rate']:.0%}, "
              f"std {best1['std_r']*100:.2f}%")

    if pair_results:
        best2 = pair_results[0]
        print(f"\n  2 笔最优: {best2['buy1']}→{best2['sell1']} | {best2['buy2']}→{best2['sell2']}")
        print(f"     周均 {best2['avg_return']*100:+.2f}%, 胜率 {best2['win_rate']:.0%}, "
              f"std {best2['std_r']*100:.2f}%")

    if single_results and pair_results:
        gain = (best2["avg_return"] - best1["avg_return"]) * 100
        print(f"\n  📊 2笔 vs 1笔: 增量 {gain:+.2f}%")

    # 最优 2 笔详情
    if pair_results:
        print(f"\n  🏆 最优 2 笔策略详情:")
        print(f"     交易1: {pair_results[0]['buy1']} → {pair_results[0]['sell1']}")
        print(f"     交易2: {pair_results[0]['buy2']} → {pair_results[0]['sell2']}")
        print(f"     周均 +{pair_results[0]['avg_return']*100:.2f}%, "
              f"胜率 {pair_results[0]['win_rate']:.0%}, "
              f"覆盖 {pair_results[0]['n_weeks']} 周")

    return {"single": single_results, "pair": pair_results}


# ============================================================
# 9. 综合建议
# ============================================================

def print_summary(cursor):
    print()
    print("=" * 70)
    print("🎯 八、综合建议")
    print("=" * 70)

    rows = fetchall(cursor, """
        WITH daily AS (
            SELECT trade_date, weekday,
                SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1)   AS d_open,
                SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt DESC), ',', 1) AS d_close
            FROM gold_prices WHERE weekday < 5
            GROUP BY trade_date, weekday
        ),
        stats AS (
            SELECT
                g.weekday,
                AVG(g.price_usd)                                AS avg_price,
                AVG((d.d_close - d.d_open) / NULLIF(d.d_open, 0)) AS avg_change,
                COUNT(DISTINCT g.trade_date)                     AS n_days,
                SUM(CASE WHEN d.d_close > d.d_open THEN 1 ELSE 0 END) AS up_days
            FROM gold_prices g
            JOIN daily d ON g.trade_date = d.trade_date
            WHERE g.weekday < 5 AND d.d_open > 0
            GROUP BY g.weekday
        )
        SELECT weekday, avg_price, avg_change,
               up_days / NULLIF(n_days, 0) AS up_prob
        FROM stats ORDER BY avg_price ASC
    """)

    print("\n  📥 最佳买入日（均价从低到高）:")
    for i, row in enumerate(rows[:3]):
        print(f"     {i+1}. {WEEKDAY_NAMES[row[0]]} - 均价 {row[1]:,.2f}, "
              f"上涨概率 {row[3]:.0%}")

    rows2 = sorted(rows, key=lambda r: r[1], reverse=True)
    print("\n  📤 最佳卖出日（均价从高到低）:")
    for i, row in enumerate(rows2[:3]):
        print(f"     {i+1}. {WEEKDAY_NAMES[row[0]]} - 均价 {row[1]:,.2f}, "
              f"上涨概率 {row[3]:.0%}")

    print("\n  ⏰ 日内时段均价:")
    hourly = fetchall(cursor, """
        SELECT hour, ROUND(AVG(price_usd), 2), COUNT(*)
        FROM gold_prices WHERE weekday < 5
        GROUP BY hour ORDER BY hour
    """)
    for h, avg, n in hourly:
        print(f"     {h:02d}:00  {avg:>10,.2f}  ({n} 条)")


# ============================================================
# 10. 绘图
# ============================================================

def plot_charts(cursor):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
    except ImportError:
        print("\n  ⚠️  未安装 matplotlib")
        return

    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle("金价周度规律分析 (MySQL)", fontsize=16, fontweight="bold")

    # Chart 1
    ax1 = axes[0, 0]
    rows = fetchall(cursor, """
        SELECT weekday, AVG(price_usd) FROM gold_prices
        WHERE weekday < 5 GROUP BY weekday ORDER BY weekday
    """)
    wds = [WEEKDAY_NAMES[r[0]] for r in rows]
    avgs = [r[1] for r in rows]
    bars = ax1.bar(wds, avgs, color=["#3498db", "#2ecc71", "#e74c3c", "#f39c12", "#9b59b6"])
    ax1.set_title("各星期几均价 (USD/盎司)")
    for bar, val in zip(bars, avgs):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f"{val:.0f}", ha="center", va="bottom", fontsize=9)

    # Chart 2
    ax2 = axes[0, 1]
    rows = fetchall(cursor, """
        SELECT g.weekday,
            SUM(CASE WHEN d_close > d_open THEN 1 ELSE 0 END)*1.0/COUNT(DISTINCT g.trade_date),
            SUM(CASE WHEN d_close < d_open THEN 1 ELSE 0 END)*1.0/COUNT(DISTINCT g.trade_date)
        FROM gold_prices g
        JOIN (
            SELECT trade_date,
                SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1) AS d_open,
                SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt DESC), ',', 1) AS d_close
            FROM gold_prices WHERE weekday < 5 GROUP BY trade_date
        ) d_cte ON g.trade_date = d_cte.trade_date
        WHERE g.weekday < 5 AND d_cte.d_open > 0
        GROUP BY g.weekday ORDER BY g.weekday
    """)
    x = range(len(rows))
    xl = [WEEKDAY_NAMES[r[0]] for r in rows]
    up = [r[1] for r in rows]
    down = [r[2] for r in rows]
    ax2.bar(x, up, label="上涨概率", color="#e74c3c", alpha=0.8)
    ax2.bar(x, down, bottom=up, label="下跌概率", color="#2ecc71", alpha=0.8)
    ax2.set_xticks(x)
    ax2.set_xticklabels(xl)
    ax2.set_title("各星期几涨跌概率")
    ax2.legend()
    ax2.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))

    # Chart 3
    ax3 = axes[1, 0]
    rows = fetchall(cursor, """
        SELECT hour, AVG(price_usd) FROM gold_prices
        WHERE weekday < 5 GROUP BY hour ORDER BY hour
    """)
    ax3.plot([r[0] for r in rows], [r[1] for r in rows], marker="o", color="#3498db", linewidth=2)
    ax3.set_title("日内小时均价走势")
    ax3.set_xlabel("小时")
    ax3.grid(True, alpha=0.3)

    # Chart 4
    ax4 = axes[1, 1]
    rows = fetchall(cursor, """
        SELECT (w_close - w_open) / NULLIF(w_open, 0) * 100
        FROM (
            SELECT year_week,
                SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1)   AS w_open,
                SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt DESC), ',', 1) AS w_close,
                COUNT(*) AS cnt
            FROM gold_prices GROUP BY year_week HAVING cnt >= 2
        ) t WHERE w_open > 0 ORDER BY year_week
    """)
    rets = [r[0] for r in rows if r[0] is not None]
    if rets:
        ax4.bar(range(len(rets)), rets, color=["#e74c3c" if r>0 else "#2ecc71" for r in rets])
        ax4.axhline(y=0, color="black", linewidth=0.5)
        up_n = sum(1 for r in rets if r > 0)
        ax4.set_title(f"周度收益率 (%)   |   上涨 {up_n}/{len(rets)} 周")
        ax4.grid(True, alpha=0.3)

    plt.tight_layout()
    out = "mysql_analysis_charts.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\n  📊 图表已保存: {out}")
    plt.close()


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="MySQL 金价分析")
    parser.add_argument("--demo", action="store_true", help="演示特定策略")
    parser.add_argument("--plot", action="store_true", help="生成图表")
    args = parser.parse_args()

    conn = get_connection()
    cursor = conn.cursor()

    show_info(cursor)

    if args.demo:
        print()
        print("=" * 70)
        print("🎯 演示: 周二 23:10 买入 → 周四 01:30 卖出")
        print("=" * 70)
        r = evaluate_trade_schedule(cursor, [(1, 23, 10, 3, 1, 30)])
        print_trade_result(r)

        print(f"\n  场景2: 周一 10:10 买入 → 周三 12:50 卖出")
        print("  " + "-" * 50)
        r2 = evaluate_trade_schedule(cursor, [(0, 10, 10, 2, 12, 50)])
        print_trade_result(r2)

        cursor.close()
        conn.close()
        return

    # 完整分析
    analyze_avg_by_weekday(cursor)
    analyze_volatility_by_weekday(cursor)
    analyze_intraday_by_weekday(cursor)
    analyze_daily_change(cursor)
    analyze_overnight_gap(cursor)
    analyze_weekly_trend(cursor)
    rank_strategies(cursor)
    print_summary(cursor)

    if args.plot:
        plot_charts(cursor)

    print("\n✅ 分析完成。")
    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
