#!/usr/bin/env python3
"""
DuckDB SQL 金价分析脚本
使用 DuckDB 直接查询 CSV 文件，实现以下分析：
  1. 各星期几均价统计（哪天最贵/最便宜）
  2. 各星期几波动率
  3. 日内按小时走势（分星期几）
  4. 各星期几涨跌概率
  5. 隔夜跳空统计
  6. 周度收益率分布
  7. 综合交易建议
  8. 自定义交易策略收益计算

用法:
    python3 scripts/sql/gold_analysis.py [--csv-dir data/] [--plot] [--demo]

依赖:
    pip install duckdb matplotlib
"""

import os
import sys
import argparse
import duckdb
from pathlib import Path

# ============================================================
# 常量
# ============================================================

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

USD_COL = '"金价(USD/盎司)"'
CNY_COL = '"金价(CNY/克)"'

# ============================================================
# 1. 数据视图创建
# ============================================================

def create_views(con, csv_dir):
    """
    创建统一的 DuckDB 视图 all_gold，合并所有 CSV 文件。
    返回行数。
    """
    csv_pattern = os.path.join(csv_dir, "gold_*.csv")

    con.execute(f"""
        CREATE OR REPLACE VIEW all_gold AS
        SELECT
            日期::DATE                          AS trade_date,
            时间::TIME                          AS trade_time,
            日期 || ' ' || 时间                  AS ts,
            strptime(日期 || ' ' || 时间, '%Y-%m-%d %H:%M:%S') AS dt,
            {USD_COL}::DOUBLE                   AS price_usd,
            {CNY_COL}::DOUBLE                   AS price_cny,
            (DAYOFWEEK(日期::DATE) + 5) % 7       AS weekday,
            HOUR(时间::TIME)                    AS hour,
            MINUTE(时间::TIME)                  AS minute,
            YEARWEEK(日期::DATE)                AS year_week
        FROM read_csv('{csv_pattern}',
            strict_mode=false,
            ignore_errors=true)
    """)

    # 每天首尾视图（使用子查询+窗口函数）
    con.execute("""
        CREATE OR REPLACE VIEW daily_summary AS
        WITH ranked AS (
            SELECT
                trade_date,
                weekday,
                dt,
                price_usd,
                ROW_NUMBER() OVER (PARTITION BY trade_date ORDER BY dt ASC)  AS rn_asc,
                ROW_NUMBER() OVER (PARTITION BY trade_date ORDER BY dt DESC) AS rn_desc
            FROM all_gold
        )
        SELECT
            trade_date,
            weekday,
            MIN(dt)          AS day_open_dt,
            MAX(CASE WHEN rn_asc = 1 THEN price_usd END)  AS open_price,
            MAX(CASE WHEN rn_desc = 1 THEN price_usd END) AS close_price,
            MAX(price_usd)   AS high_price,
            MIN(price_usd)   AS low_price,
            COUNT(*)         AS tick_count
        FROM ranked
        GROUP BY trade_date, weekday
    """)

    # 每天每小时均价视图
    con.execute("""
        CREATE OR REPLACE VIEW hourly_avg AS
        SELECT
            trade_date,
            weekday,
            hour,
            AVG(price_usd) AS avg_price,
            COUNT(*)       AS tick_count
        FROM all_gold
        GROUP BY trade_date, weekday, hour
    """)

    row_count = con.execute("SELECT COUNT(*) FROM all_gold").fetchone()[0]
    return row_count


# ============================================================
# 2. 分析 1：各星期几均价
# ============================================================

def analyze_avg_by_weekday(con):
    print()
    print("=" * 70)
    print("📊 一、各星期几价格统计")
    print("=" * 70)

    result = con.execute(f"""
        SELECT
            weekday,
            COUNT(*)                            AS n,
            ROUND(AVG(price_usd), 2)            AS avg_price,
            ROUND(MEDIAN(price_usd), 2)         AS med_price,
            ROUND(MAX(price_usd), 2)            AS max_price,
            ROUND(MIN(price_usd), 2)            AS min_price,
            ROUND(STDDEV_SAMP(price_usd), 2)    AS std_price
        FROM all_gold
        WHERE weekday < 5
        GROUP BY weekday
        ORDER BY weekday
    """).fetchall()

    print(f"  {'星期':<6} {'记录数':>7} {'均价(USD)':>12} {'中位(USD)':>12} {'最高(USD)':>12} {'最低(USD)':>12} {'波动率(USD)':>12}")
    print("  " + "-" * 70)

    for wd, n, avg, med, mx, mn, std in result:
        print(f"  {WEEKDAY_NAMES[wd]:<6} {n:>7} {avg:>12,.2f} {med:>12,.2f} {mx:>12,.2f} {mn:>12,.2f} {std:>12,.2f}")

    cheapest = min(result, key=lambda r: r[2])
    dearest  = max(result, key=lambda r: r[2])
    print(f"\n  💰 均价最便宜: {WEEKDAY_NAMES[cheapest[0]]} ({cheapest[2]:,.2f}) → 适合买入")
    print(f"  💸 均价最贵:   {WEEKDAY_NAMES[dearest[0]]} ({dearest[2]:,.2f}) → 适合卖出")


# ============================================================
# 3. 分析 2：各星期几日内振幅
# ============================================================

def analyze_volatility_by_weekday(con):
    print()
    print("=" * 70)
    print("📈 二、各星期几日振幅（日内波动幅度）")
    print("=" * 70)

    result = con.execute("""
        SELECT
            weekday,
            COUNT(DISTINCT trade_date)                  AS n_days,
            ROUND(AVG((high_price - low_price) / NULLIF(open_price, 0)), 6) AS avg_amplitude,
            ROUND(MAX((high_price - low_price) / NULLIF(open_price, 0)), 6) AS max_amplitude,
            ROUND(MIN((high_price - low_price) / NULLIF(open_price, 0)), 6) AS min_amplitude
        FROM daily_summary
        WHERE weekday < 5 AND open_price > 0
        GROUP BY weekday
        ORDER BY weekday
    """).fetchall()

    print(f"  {'星期':<6} {'交易日数':>8} {'平均日振幅':>12} {'最大日振幅':>12} {'最小日振幅':>12}")
    print("  " + "-" * 55)

    for wd, n_days, avg_amp, max_amp, min_amp in result:
        print(f"  {WEEKDAY_NAMES[wd]:<6} {n_days:>8} {avg_amp*100:>+11.2f}% {max_amp*100:>+11.2f}% {min_amp*100:>+11.2f}%")

    most_volatile = max(result, key=lambda r: r[2])
    print(f"\n  ⚡ 波动最大: {WEEKDAY_NAMES[most_volatile[0]]} (平均日振幅 {most_volatile[2]*100:+.2f}%)")


# ============================================================
# 4. 分析 3：日内按小时走势（分星期几）
# ============================================================

def analyze_intraday_by_weekday(con):
    print()
    print("=" * 70)
    print("🕐 三、各星期几分时段走势（按小时）")
    print("=" * 70)

    for wd in range(5):
        result = con.execute("""
            SELECT
                h.hour,
                AVG(h.avg_price)                            AS hour_avg,
                SUM(h.tick_count)                           AS n,
                AVG((h.avg_price - d.open_price) / NULLIF(d.open_price, 0)) AS rel_open
            FROM hourly_avg h
            JOIN daily_summary d
                ON h.trade_date = d.trade_date
                AND d.open_price > 0
            WHERE h.weekday = ?
            GROUP BY h.hour
            ORDER BY h.hour
        """, [wd]).fetchall()

        if not result:
            continue

        print(f"\n  {WEEKDAY_NAMES[wd]}:")
        print(f"    {'小时':<6} {'均价(USD)':>12} {'记录数':>7} {'相对开盘':>10}")
        print("    " + "-" * 40)

        prev_avg = None
        for hour, avg, n, rel in result:
            arrow = ""
            if prev_avg is not None:
                if avg > prev_avg:
                    arrow = "  ↑"
                elif avg < prev_avg:
                    arrow = "  ↓"
                else:
                    arrow = "  →"
            else:
                arrow = "  ●"
            prev_avg = avg
            print(f"    {hour:02d}:00  {avg:>12,.2f} {n:>7} {rel*100:>+9.2f}%{arrow}")


# ============================================================
# 5. 分析 4：各星期几涨跌概率
# ============================================================

def analyze_daily_change(con):
    print()
    print("=" * 70)
    print("📉 四、各星期几涨跌统计")
    print("=" * 70)

    result = con.execute("""
        SELECT
            weekday,
            COUNT(*)                                            AS n_days,
            SUM(CASE WHEN close_price > open_price THEN 1 ELSE 0 END) AS up_days,
            SUM(CASE WHEN close_price < open_price THEN 1 ELSE 0 END) AS down_days,
            ROUND(AVG((close_price - open_price) / NULLIF(open_price, 0)), 6) AS avg_change,
            ROUND(AVG(CASE WHEN close_price > open_price
                THEN (close_price - open_price) / open_price END), 6) AS avg_up,
            ROUND(AVG(CASE WHEN close_price < open_price
                THEN (close_price - open_price) / open_price END), 6) AS avg_down
        FROM daily_summary
        WHERE weekday < 5 AND open_price > 0
        GROUP BY weekday
        ORDER BY weekday
    """).fetchall()

    print(f"  {'星期':<6} {'天数':>6} {'上涨天数':>8} {'下跌天数':>8} {'上涨概率':>10} {'平均涨跌':>12} {'平均涨幅':>12} {'平均跌幅':>12}")
    print("  " + "-" * 80)

    for wd, n, up, down, avg_chg, avg_up, avg_down in result:
        up_prob = up / n if n else 0
        print(f"  {WEEKDAY_NAMES[wd]:<6} {n:>6} {up:>8} {down:>8} {up_prob:>9.0%} "
              f"{avg_chg*100:>+11.2f}% {(avg_up or 0)*100:>+11.2f}% {(avg_down or 0)*100:>+11.2f}%")

    best_buy = max(result, key=lambda r: r[3] / r[1] if r[1] else 0)
    best_sell = max(result, key=lambda r: r[2] / r[1] if r[1] else 0)
    print(f"\n  📌 最可能下跌（适合买入）: {WEEKDAY_NAMES[best_buy[0]]}")
    print(f"  📌 最可能上涨（适合卖出）: {WEEKDAY_NAMES[best_sell[0]]}")


# ============================================================
# 6. 分析 5：隔夜跳空（前日收盘 → 次日开盘）
# ============================================================

def analyze_overnight_gap(con):
    print()
    print("=" * 70)
    print("🌙 五、隔夜跳空统计（前日收盘 → 次日开盘）")
    print("=" * 70)

    result = con.execute("""
        WITH ordered AS (
            SELECT
                trade_date,
                weekday,
                close_price,
                open_price,
                LEAD(trade_date)  OVER (ORDER BY trade_date) AS next_date,
                LEAD(weekday)     OVER (ORDER BY trade_date) AS next_weekday,
                LEAD(open_price)  OVER (ORDER BY trade_date) AS next_open
            FROM daily_summary
        ),
        gaps AS (
            SELECT
                weekday       AS from_wd,
                next_weekday  AS to_wd,
                (next_open - close_price) / NULLIF(close_price, 0) AS gap
            FROM ordered
            WHERE next_date IS NOT NULL
                AND close_price > 0 AND next_open > 0
                AND weekday < 5 AND next_weekday < 5
        )
        SELECT
            from_wd,
            to_wd,
            COUNT(*)                                          AS n,
            ROUND(AVG(gap), 6)                                AS avg_gap,
            ROUND(MAX(gap), 6)                                AS max_gap,
            ROUND(MIN(gap), 6)                                AS min_gap
        FROM gaps
        GROUP BY from_wd, to_wd
        ORDER BY from_wd, to_wd
    """).fetchall()

    print(f"  {'前日':<6} → {'次日':<6} {'跳空次数':>8} {'平均跳空':>12} {'最大跳空':>12} {'最小跳空':>12}")
    print("  " + "-" * 60)

    for fw, tw, n, avg_g, max_g, min_g in result:
        print(f"  {WEEKDAY_NAMES[fw]:<6} → {WEEKDAY_NAMES[tw]:<6} {n:>8} "
              f"{avg_g*100:>+11.2f}% {max_g*100:>+11.2f}% {min_g*100:>+11.2f}%")


# ============================================================
# 7. 分析 6：周度收益率分布
# ============================================================

def analyze_weekly_trend(con):
    print()
    print("=" * 70)
    print("📅 六、周度收益率分布")
    print("=" * 70)

    result = con.execute("""
        WITH ranked AS (
            SELECT
                year_week,
                dt,
                price_usd,
                ROW_NUMBER() OVER (PARTITION BY year_week ORDER BY dt ASC)  AS rn_asc,
                ROW_NUMBER() OVER (PARTITION BY year_week ORDER BY dt DESC) AS rn_desc,
                COUNT(*) OVER (PARTITION BY year_week) AS tick_count
            FROM all_gold
        ),
        aggregated AS (
            SELECT
                year_week,
                MAX(CASE WHEN rn_asc = 1 THEN price_usd END)  AS week_open,
                MAX(CASE WHEN rn_desc = 1 THEN price_usd END) AS week_close,
                MAX(tick_count) AS tick_count
            FROM ranked
            GROUP BY year_week
        ),
        week_returns AS (
            SELECT
                year_week,
                (week_close - week_open) / NULLIF(week_open, 0) AS week_return
            FROM aggregated
            WHERE week_open > 0 AND tick_count >= 2
        )
        SELECT
            COUNT(*)                                                  AS total_weeks,
            SUM(CASE WHEN week_return > 0 THEN 1 ELSE 0 END)          AS up_weeks,
            SUM(CASE WHEN week_return < 0 THEN 1 ELSE 0 END)          AS down_weeks,
            ROUND(AVG(week_return) * 100, 4)                          AS avg_return,
            ROUND(MAX(week_return) * 100, 4)                          AS max_return,
            ROUND(MIN(week_return) * 100, 4)                          AS min_return
        FROM week_returns
    """).fetchone()

    total, up, down, avg_ret, max_ret, min_ret = result
    print(f"  总周数: {total}")
    print(f"  上涨周: {up} ({up/total:.0%})" if total else "  上涨周: 0")
    print(f"  下跌周: {down} ({down/total:.0%})" if total else "  下跌周: 0")
    print(f"  平均周收益率: {avg_ret:+.2f}%")
    print(f"  最大周涨幅:   {max_ret:+.2f}%")
    print(f"  最大周跌幅:   {min_ret:+.2f}%")


# ============================================================
# 8. 自定义交易策略评估（核心通用函数）
# ============================================================

def evaluate_trade_schedule(con, schedule, min_weeks_ratio=0.4):
    """
    评估自定义交易策略的收益。

    参数:
        con:              DuckDB 连接
        schedule:         交易时间数组 [(buy_wd, buy_h, buy_m, sell_wd, sell_h, sell_m), ...]
                          wd: 0=周一, 1=周二, ..., 4=周五
        min_weeks_ratio:  最低有效周数比例

    返回:
        dict: 包含完整的收益分析信息
    """
    N = len(schedule)

    weeks = [r[0] for r in con.execute(
        "SELECT DISTINCT year_week FROM all_gold ORDER BY year_week"
    ).fetchall()]

    total_weeks = len(weeks)
    all_returns = []
    trade_rets = [[] for _ in range(N)]
    week_details = []

    for yw in weeks:
        rows = con.execute("""
            SELECT weekday, hour, minute, price_usd, dt
            FROM all_gold
            WHERE year_week = ?
            ORDER BY dt
        """, [yw]).fetchall()

        if len(rows) < 10:
            continue

        series = [
            {"wd": r[0], "h": r[1], "m": r[2], "price": r[3], "dt": r[4]}
            for r in rows
        ]

        used = set()
        executed = []
        per_trade = []

        for ti, (bw, bh, bm, sw, sh, sm) in enumerate(schedule):
            best_b, best_b_dist = None, float("inf")
            for i, s in enumerate(series):
                if i in used:
                    continue
                if s["wd"] == bw and s["h"] == bh:
                    d = abs(s["m"] - bm)
                    if d < best_b_dist:
                        best_b_dist = d
                        best_b = (i, s["price"])

            if best_b is None:
                break

            best_s, best_s_dist = None, float("inf")
            for i, s in enumerate(series):
                if i in used or i <= best_b[0]:
                    continue
                if s["wd"] == sw and s["h"] == sh:
                    d = abs(s["m"] - sm)
                    if d < best_s_dist:
                        best_s_dist = d
                        best_s = (i, s["price"])

            if best_s is None:
                break

            ret = (best_s[1] - best_b[1]) / best_b[1]
            executed.append(ret)
            per_trade.append(ret)
            trade_rets[ti].append(ret)
            used.add(best_b[0])
            used.add(best_s[0])

        if len(executed) == N:
            all_returns.append(sum(executed))
            week_details.append({
                "week_label": str(yw),
                "per_trade_rets": per_trade,
                "total_ret": sum(executed),
            })

    min_weeks = max(3, total_weeks * min_weeks_ratio)

    if len(all_returns) < min_weeks:
        return None

    def safe_mean(lst):
        return sum(lst) / len(lst) if lst else 0

    def safe_stdev(lst):
        if len(lst) < 2:
            return 0
        m = safe_mean(lst)
        return (sum((x - m)**2 for x in lst) / (len(lst) - 1)) ** 0.5

    per_trade_summary = []
    for ti, (bw, bh, bm, sw, sh, sm) in enumerate(schedule):
        tr = trade_rets[ti]
        per_trade_summary.append({
            "buy": f"{WEEKDAY_NAMES[bw]} {bh:02d}:{bm:02d}",
            "sell": f"{WEEKDAY_NAMES[sw]} {sh:02d}:{sm:02d}",
            "avg_return": safe_mean(tr),
            "win_rate": sum(1 for x in tr if x > 0) / len(tr) if tr else 0,
            "n_trades": len(tr),
        })

    avg_ret = safe_mean(all_returns)

    return {
        "avg_return": avg_ret,
        "n_weeks": len(all_returns),
        "total_weeks": total_weeks,
        "returns": all_returns,
        "trade_rets": trade_rets,
        "win_rate": sum(1 for r in all_returns if r > 0) / len(all_returns),
        "max_r": max(all_returns) if all_returns else 0,
        "min_r": min(all_returns) if all_returns else 0,
        "std_r": safe_stdev(all_returns),
        "schedule": schedule,
        "week_details": week_details,
        "per_trade_summary": per_trade_summary,
    }


def print_trade_result(result):
    """格式化输出交易策略评估结果。"""
    if result is None:
        print("\n  ❌ 有效交易周数不足，无法计算收益。")
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
        print(f"         均值: {ts['avg_return']*100:+.2f}%, 胜率: {ts['win_rate']:.0%}, 笔数: {ts['n_trades']}")

    print(f"\n  📋 最近 {min(10, len(result['week_details']))} 周收益明细:")
    hdr = f"     {'周':<10}"
    for i in range(len(result["schedule"])):
        hdr += f" {'T'+str(i+1):>8}"
    hdr += f" {'合计':>8}"
    print(hdr)
    print("     " + "-" * (10 + 9 * len(result["schedule"]) + 8))
    for wd in result["week_details"][-10:]:
        line = f"     {wd['week_label']:<10}"
        for rt in wd["per_trade_rets"]:
            line += f" {rt*100:>+7.2f}%"
        line += f" {wd['total_ret']*100:>+7.2f}%"
        print(line)


# ============================================================
# 9. 策略搜索（SQL 驱动的枚举优化）
# ============================================================

def search_best_strategies(con, top_n=10):
    """枚举所有单笔交易策略，找出最优的。"""
    print()
    print("=" * 70)
    print("🔍 七、最优策略搜索（SQL 枚举）")
    print("=" * 70)

    all_hours = list(range(10, 24)) + [0, 1]
    results = []

    print("  ⏳ 枚举中...")
    total = 0
    for bw in range(5):
        for sw in range(bw, 5):
            for bh in all_hours:
                for sh in all_hours:
                    buy_order = bw * 2400 + bh * 60 + 10
                    sell_order = sw * 2400 + sh * 60 + 50
                    if buy_order >= sell_order:
                        continue

                    total += 1
                    r = evaluate_trade_schedule(
                        con,
                        [(bw, bh, 10, sw, sh, 50)],
                        min_weeks_ratio=0.5,
                    )
                    if r:
                        results.append({
                            "buy": f"{WEEKDAY_NAMES[bw]} {bh:02d}:10",
                            "sell": f"{WEEKDAY_NAMES[sw]} {sh:02d}:50",
                            "avg_return": r["avg_return"],
                            "win_rate": r["win_rate"],
                            "n_weeks": r["n_weeks"],
                            "max_r": r["max_r"],
                            "min_r": r["min_r"],
                            "schedule": [(bw, bh, 10, sw, sh, 50)],
                            "result": r,
                        })

    results.sort(key=lambda x: -x["avg_return"])
    print(f"  枚举 {total} 个组合, 有效 {len(results)} 个")

    print(f"\n  📊 Top {min(top_n, len(results))} 单笔策略:")
    print(f"  {'#':<3} {'买入':<13} {'卖出':<13} {'周均':>8} {'胜率':>6} {'周数':>4} {'最大':>8} {'最小':>8}")
    print("  " + "-" * 63)

    for i, r in enumerate(results[:top_n]):
        print(f"  {i+1:<3} {r['buy']:<13} {r['sell']:<13} "
              f"{r['avg_return']*100:>+7.2f}% {r['win_rate']:>5.0%} {r['n_weeks']:>4} "
              f"{r['max_r']*100:>+7.2f}% {r['min_r']*100:>+7.2f}%")

    if results:
        best = results[0]
        print(f"\n  🏆 最优策略详情:")
        print_trade_result(best["result"])

    return results


# ============================================================
# 10. 综合建议
# ============================================================

def print_summary(con):
    print()
    print("=" * 70)
    print("🎯 八、综合建议")
    print("=" * 70)

    result = con.execute("""
        WITH stats AS (
            SELECT
                d.weekday,
                AVG(a.price_usd)                                             AS avg_price,
                AVG((d.close_price - d.open_price) / NULLIF(d.open_price, 0)) AS avg_change,
                COUNT(*)                                                     AS n_days,
                SUM(CASE WHEN d.close_price > d.open_price THEN 1 ELSE 0 END) AS up_days
            FROM daily_summary d
            JOIN all_gold a ON a.trade_date = d.trade_date
            WHERE d.weekday < 5 AND d.open_price > 0
            GROUP BY d.weekday
        ),
        scored AS (
            SELECT
                weekday,
                avg_price,
                avg_change,
                up_days * 1.0 / NULLIF(n_days, 0) AS up_prob,
                -avg_price / 100 + (1.0 - up_days * 1.0 / NULLIF(n_days, 0)) * 10 AS buy_score,
                avg_price / 100 + (up_days * 1.0 / NULLIF(n_days, 0)) * 10      AS sell_score
            FROM stats
        )
        SELECT * FROM scored ORDER BY buy_score DESC
    """).fetchall()

    print(f"\n  📥 最佳买入日（综合价格低+下跌概率高）:")
    for i, row in enumerate(result[:3]):
        wd, avg_p, avg_c, up_prob, buy_s, sell_s = row
        print(f"     {i+1}. {WEEKDAY_NAMES[wd]} - 均价 {avg_p:,.2f}, "
              f"上涨概率 {up_prob:.0%}, 平均日涨跌 {avg_c*100:+.2f}%")

    result_sell = sorted(result, key=lambda r: r[5], reverse=True)
    print(f"\n  📤 最佳卖出日（综合价格高+上涨概率高）:")
    for i, row in enumerate(result_sell[:3]):
        wd, avg_p, avg_c, up_prob, buy_s, sell_s = row
        print(f"     {i+1}. {WEEKDAY_NAMES[wd]} - 均价 {avg_p:,.2f}, "
              f"上涨概率 {up_prob:.0%}, 平均日涨跌 {avg_c*100:+.2f}%")

    print(f"\n  ⏰ 日内时段规律（所有工作日聚合）:")
    hourly = con.execute("""
        SELECT
            hour,
            ROUND(AVG(price_usd), 2) AS avg_price,
            COUNT(*)                  AS n
        FROM all_gold
        WHERE weekday < 5
        GROUP BY hour
        ORDER BY hour
    """).fetchall()
    for hour, avg_p, n in hourly:
        print(f"     {hour:02d}:00  均价 {avg_p:,.2f}  (样本数: {n})")


# ============================================================
# 11. 绘图
# ============================================================

def plot_charts(con):
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
    fig.suptitle("金价周度规律分析 (DuckDB SQL)", fontsize=16, fontweight="bold")

    # Chart 1: 星期几均价
    ax1 = axes[0, 0]
    data = con.execute("""
        SELECT weekday, AVG(price_usd) FROM all_gold
        WHERE weekday < 5 GROUP BY weekday ORDER BY weekday
    """).fetchall()
    wds = [WEEKDAY_NAMES[int(r[0])] for r in data]
    avgs = [r[1] for r in data]
    bars = ax1.bar(wds, avgs, color=["#3498db", "#2ecc71", "#e74c3c", "#f39c12", "#9b59b6"])
    ax1.set_title("各星期几均价 (USD/盎司)")
    ax1.set_ylabel("USD/盎司")
    for bar, val in zip(bars, avgs):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                 f"{val:.0f}", ha="center", va="bottom", fontsize=9)

    # Chart 2: 涨跌概率
    ax2 = axes[0, 1]
    prob_data = con.execute("""
        SELECT weekday,
            SUM(CASE WHEN close_price > open_price THEN 1 ELSE 0 END)*1.0/COUNT(*) AS up_prob,
            SUM(CASE WHEN close_price < open_price THEN 1 ELSE 0 END)*1.0/COUNT(*) AS down_prob
        FROM daily_summary WHERE weekday < 5 AND open_price > 0
        GROUP BY weekday ORDER BY weekday
    """).fetchall()
    x_labels = [WEEKDAY_NAMES[int(r[0])] for r in prob_data]
    x = range(len(prob_data))
    up_vals = [r[1] for r in prob_data]
    down_vals = [r[2] for r in prob_data]
    ax2.bar(x, up_vals, label="上涨概率", color="#e74c3c", alpha=0.8)
    ax2.bar(x, down_vals, bottom=up_vals, label="下跌概率", color="#2ecc71", alpha=0.8)
    ax2.set_xticks(x)
    ax2.set_xticklabels(x_labels)
    ax2.set_title("各星期几涨跌概率")
    ax2.set_ylabel("概率")
    ax2.legend()
    ax2.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))

    # Chart 3: 日内均价走势
    ax3 = axes[1, 0]
    hourly = con.execute("""
        SELECT hour, AVG(price_usd) FROM all_gold
        WHERE weekday < 5 GROUP BY hour ORDER BY hour
    """).fetchall()
    hours = [r[0] for r in hourly]
    hour_avgs = [r[1] for r in hourly]
    ax3.plot(hours, hour_avgs, marker="o", color="#3498db", linewidth=2)
    ax3.set_title("日内小时均价走势（工作日）")
    ax3.set_xlabel("小时")
    ax3.set_ylabel("USD/盎司")
    ax3.grid(True, alpha=0.3)

    # Chart 4: 周度收益率
    ax4 = axes[1, 1]
    week_rets = con.execute("""
        WITH ranked AS (
            SELECT year_week, dt, price_usd,
                ROW_NUMBER() OVER (PARTITION BY year_week ORDER BY dt ASC) AS rn_asc,
                ROW_NUMBER() OVER (PARTITION BY year_week ORDER BY dt DESC) AS rn_desc,
                COUNT(*) OVER (PARTITION BY year_week) AS cnt
            FROM all_gold
        ),
        w AS (
            SELECT year_week,
                MAX(CASE WHEN rn_asc = 1 THEN price_usd END) AS w_open,
                MAX(CASE WHEN rn_desc = 1 THEN price_usd END) AS w_close,
                MAX(cnt) AS cnt
            FROM ranked
            GROUP BY year_week
            HAVING MAX(cnt) >= 2
        )
        SELECT (w_close - w_open) / NULLIF(w_open, 0) * 100
        FROM w WHERE w_open > 0 ORDER BY year_week
    """).fetchall()
    week_rets = [r[0] for r in week_rets]
    if week_rets:
        ax4.bar(range(len(week_rets)), week_rets,
                color=["#e74c3c" if r > 0 else "#2ecc71" for r in week_rets])
        ax4.axhline(y=0, color="black", linewidth=0.5)
        up_count = sum(1 for r in week_rets if r > 0)
        ax4.set_title(f"周度收益率 (%)   |   上涨 {up_count}/{len(week_rets)} 周")
        ax4.set_xlabel("周序号")
        ax4.set_ylabel("收益率 (%)")
        ax4.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = "sql_analysis_charts.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"\n  📊 图表已保存: {out_path}")
    plt.close()


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="DuckDB SQL 金价分析")
    parser.add_argument("--csv-dir", default="data", help="CSV 数据目录")
    parser.add_argument("--plot", action="store_true", help="生成图表")
    parser.add_argument("--demo", action="store_true", help="演示特定策略")
    parser.add_argument("--search", action="store_true", help="搜索最优策略")
    args = parser.parse_args()

    csv_dir = args.csv_dir
    if not os.path.isdir(csv_dir):
        print(f"错误: 目录不存在: {csv_dir}")
        sys.exit(1)

    con = duckdb.connect(":memory:")

    print("⏳ 加载数据 (DuckDB 直接查询 CSV)...")
    row_count = create_views(con, csv_dir)

    date_range = con.execute("SELECT MIN(trade_date), MAX(trade_date) FROM all_gold").fetchone()
    print(f"✅ 加载完成: {row_count} 条记录")
    print(f"   日期范围: {date_range[0]} ~ {date_range[1]}")
    print(f"   数据跨度: {(date_range[1] - date_range[0]).days} 天")

    if args.demo:
        print()
        print("=" * 70)
        print("🎯 特定场景演示")
        print("=" * 70)
        print(f"\n  场景1: 周二 23:10 买入 → 周四 01:30 卖出")
        print("  " + "-" * 50)
        r1 = evaluate_trade_schedule(con, [(1, 23, 10, 3, 1, 30)])
        print_trade_result(r1)

        print(f"\n  场景2: 周一 10:10 买入 → 周三 12:50 卖出")
        print("  " + "-" * 50)
        r2 = evaluate_trade_schedule(con, [(0, 10, 10, 2, 12, 50)])
        print_trade_result(r2)
        con.close()
        return

    analyze_avg_by_weekday(con)
    analyze_volatility_by_weekday(con)
    analyze_intraday_by_weekday(con)
    analyze_daily_change(con)
    analyze_overnight_gap(con)
    analyze_weekly_trend(con)
    search_best_strategies(con, top_n=10)
    print_summary(con)

    if args.plot:
        plot_charts(con)

    print("\n✅ 分析完成。")
    con.close()


if __name__ == "__main__":
    main()
