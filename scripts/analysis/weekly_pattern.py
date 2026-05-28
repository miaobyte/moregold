#!/usr/bin/env python3
"""
金价周度规律分析脚本
分析 5 分钟级金价数据的每周规律，包括：
  1. 各星期几的平均价格（哪天最贵/最便宜）
  2. 星期几的波动率最大
  3. 一周内每天的日内走势（按小时聚合）
  4. 星期几的涨跌概率与平均涨跌幅
  5. 最佳买入日 / 最佳卖出日
  6. 周度收益率分布

用法:
    python3 weekly_pattern.py [--plot] [--csv-dir data/]
"""

import os
import sys
import csv
import argparse
from collections import defaultdict
from datetime import datetime
from statistics import mean, stdev, median

# ============================================================
# 1. 数据加载
# ============================================================

# 兼容不同版本的列名
USD_COLUMNS = ["金价(USD/盎司)", "金价(USD)"]
CNY_COLUMNS = ["金价(CNY/克)", "金价(CNY)"]


def load_all_data(csv_dir: str) -> list[dict]:
    """
    加载 data 目录下所有 gold_*.csv 文件，返回记录列表。
    每条记录: {date_str, time_str, datetime, weekday, hour, usd, cny}
    """
    records = []
    for fname in sorted(os.listdir(csv_dir)):
        if not fname.startswith("gold_") or not fname.endswith(".csv"):
            continue
        fpath = os.path.join(csv_dir, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            # 自动匹配列名
            usd_col = next((c for c in USD_COLUMNS if c in fieldnames), None)
            cny_col = next((c for c in CNY_COLUMNS if c in fieldnames), None)
            if not usd_col:
                print(f"  ⚠️  跳过 {fname}: 找不到 USD 列 (可用列: {fieldnames})")
                continue
            for row in reader:
                date_str = row["日期"].strip()
                time_str = row["时间"].strip()
                try:
                    usd = float(row[usd_col])
                    cny = float(row[cny_col]) if cny_col else 0.0
                except (ValueError, KeyError):
                    continue
                dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
                records.append({
                    "date_str": date_str,
                    "time_str": time_str,
                    "datetime": dt,
                    "weekday": dt.weekday(),         # 0=Mon, 6=Sun
                    "hour": dt.hour,
                    "usd": usd,
                    "cny": cny,
                })
    records.sort(key=lambda r: r["datetime"])
    return records


# ============================================================
# 2. 工具函数
# ============================================================

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

def fmt_usd(v):
    return f"{v:,.2f}"

def fmt_cny(v):
    return f"{v:,.2f}"

def pct(v):
    return f"{v*100:+.2f}%"


# ============================================================
# 3. 分析 1：各星期几的平均价格
# ============================================================

def analyze_avg_by_weekday(records):
    """按星期几分组，统计平均 / 中位 / 最高 / 最低价格。"""
    groups = defaultdict(list)
    for r in records:
        groups[r["weekday"]].append(r)

    print("=" * 70)
    print("📊 一、各星期几价格统计")
    print("=" * 70)
    print(f"{'星期':<6} {'记录数':>7} {'均价(USD)':>12} {'中位(USD)':>12} {'最高(USD)':>12} {'最低(USD)':>12} {'波动率(USD)':>12}")
    print("-" * 70)

    for wd in range(7):
        if wd not in groups:
            continue
        recs = groups[wd]
        usds = [r["usd"] for r in recs]
        avg_u = mean(usds)
        med_u = median(usds)
        max_u = max(usds)
        min_u = min(usds)
        vol_u = stdev(usds) if len(usds) >= 2 else 0
        print(f"{WEEKDAY_NAMES[wd]:<6} {len(recs):>7} {fmt_usd(avg_u):>12} {fmt_usd(med_u):>12} {fmt_usd(max_u):>12} {fmt_usd(min_u):>12} {fmt_usd(vol_u):>12}")

    # 按均价排序
    sorted_days = sorted(groups.items(), key=lambda x: mean([r["usd"] for r in x[1]]))
    cheapest = sorted_days[0]
    dearest = sorted_days[-1]
    print()
    print(f"💰 均价最便宜: {WEEKDAY_NAMES[cheapest[0]]} ({fmt_usd(mean([r['usd'] for r in cheapest[1]]))}) → 适合买入")
    print(f"💸 均价最贵:   {WEEKDAY_NAMES[dearest[0]]} ({fmt_usd(mean([r['usd'] for r in dearest[1]]))}) → 适合卖出")


# ============================================================
# 4. 分析 2：各星期几的波动率
# ============================================================

def analyze_volatility_by_weekday(records):
    """按星期几计算日振幅（每天最高-最低）/ 开盘价。"""
    daily_groups = defaultdict(list)
    for r in records:
        daily_groups[(r["date_str"], r["weekday"])].append(r)

    wd_amplitudes = defaultdict(list)
    for (ds, wd), recs in daily_groups.items():
        usds = [r["usd"] for r in recs]
        if not usds:
            continue
        open_p = usds[0]
        high = max(usds)
        low = min(usds)
        amplitude = (high - low) / open_p if open_p else 0
        wd_amplitudes[wd].append(amplitude)

    print()
    print("=" * 70)
    print("📈 二、各星期几日振幅（日内波动幅度）")
    print("=" * 70)
    print(f"{'星期':<6} {'交易日数':>8} {'平均日振幅':>12} {'最大日振幅':>12} {'最小日振幅':>12}")
    print("-" * 60)

    for wd in range(7):
        if wd not in wd_amplitudes:
            continue
        amps = wd_amplitudes[wd]
        print(f"{WEEKDAY_NAMES[wd]:<6} {len(amps):>8} {pct(mean(amps)):>12} {pct(max(amps)):>12} {pct(min(amps)):>12}")

    most_volatile = max(wd_amplitudes.items(), key=lambda x: mean(x[1]))
    print(f"\n⚡ 波动最大: {WEEKDAY_NAMES[most_volatile[0]]} (平均日振幅 {pct(mean(most_volatile[1]))})")


# ============================================================
# 5. 分析 3：日内按小时走势（分星期几）— 修复版
# ============================================================

def analyze_intraday_by_weekday(records):
    """
    按星期几 + 小时分组，计算每小时均价。
    相对开盘 = 每小时均价相对于当天开盘价的涨跌幅，再取均值。
    """
    # 先按天分组
    daily = defaultdict(list)
    for r in records:
        daily[(r["date_str"], r["weekday"])].append(r)

    # 计算每天每小时的相对涨跌
    # wd_hour_relatives[weekday][hour] = [相对涨跌1, 相对涨跌2, ...]
    wd_hour_relatives = defaultdict(lambda: defaultdict(list))

    for (ds, wd), recs in daily.items():
        if not recs:
            continue
        day_open = recs[0]["usd"]
        if not day_open:
            continue
        hour_prices = defaultdict(list)
        for r in recs:
            hour_prices[r["hour"]].append(r["usd"])
        for h, prices in hour_prices.items():
            h_avg = mean(prices)
            rel = (h_avg - day_open) / day_open
            wd_hour_relatives[wd][h].append(rel)

    # 计算绝对均价（用于展示实际价格）
    wd_hour_abs = defaultdict(lambda: defaultdict(list))
    for r in records:
        wd_hour_abs[r["weekday"]][r["hour"]].append(r["usd"])

    print()
    print("=" * 70)
    print("🕐 三、各星期几分时段走势（按小时）")
    print("=" * 70)

    for wd in range(5):  # 只展示周一到周五
        hours = sorted(wd_hour_relatives[wd].keys())
        if not hours:
            continue
        print(f"\n{WEEKDAY_NAMES[wd]}:")
        print(f"  {'小时':<6} {'均价(USD)':>12} {'记录数':>7} {'相对开盘':>10} {'走势':>8}")
        print("  " + "-" * 48)

        # 构建走势字符串
        prev = None
        for h in hours:
            abs_avg = mean(wd_hour_abs[wd][h])
            n = len(wd_hour_abs[wd][h])
            rel = mean(wd_hour_relatives[wd][h])
            # 箭头：与前一小时比较
            arrow = ""
            if prev is not None:
                if abs_avg > prev:
                    arrow = "  ↑"
                elif abs_avg < prev:
                    arrow = "  ↓"
                else:
                    arrow = "  →"
            else:
                arrow = "  ●"  # 起点
            prev = abs_avg
            print(f"  {h:02d}:00  {fmt_usd(abs_avg):>12} {n:>7} {pct(rel):>10}{arrow}")


# ============================================================
# 6. 分析 4：星期几的涨跌概率
# ============================================================

def analyze_daily_change(records):
    """按天计算涨跌，汇总到星期几。"""
    daily = defaultdict(list)
    for r in records:
        daily[(r["date_str"], r["weekday"])].append(r)

    wd_changes = defaultdict(list)
    for (ds, wd), recs in daily.items():
        if not recs:
            continue
        open_p = recs[0]["usd"]
        close_p = recs[-1]["usd"]
        change = (close_p - open_p) / open_p if open_p else 0
        wd_changes[wd].append(change)

    print()
    print("=" * 70)
    print("📉 四、各星期几涨跌统计")
    print("=" * 70)
    print(f"{'星期':<6} {'天数':>6} {'上涨天数':>8} {'下跌天数':>8} {'上涨概率':>10} {'平均涨跌':>12} {'平均涨幅(涨日)':>14} {'平均跌幅(跌日)':>14}")
    print("-" * 85)

    for wd in range(7):
        if wd not in wd_changes:
            continue
        changes = wd_changes[wd]
        up_count = sum(1 for c in changes if c > 0)
        down_count = sum(1 for c in changes if c < 0)
        up_prob = up_count / len(changes) if changes else 0
        avg_change = mean(changes)
        avg_up = mean([c for c in changes if c > 0]) if up_count else 0
        avg_down = mean([c for c in changes if c < 0]) if down_count else 0
        print(f"{WEEKDAY_NAMES[wd]:<6} {len(changes):>6} {up_count:>8} {down_count:>8} {up_prob:>9.0%} {pct(avg_change):>12} {pct(avg_up):>14} {pct(avg_down):>14}")

    # 最佳买入日（最可能下跌）和最佳卖出日（最可能上涨）
    best_buy = max(wd_changes.items(), key=lambda x: sum(1 for c in x[1] if c < 0) / len(x[1]))
    best_sell = max(wd_changes.items(), key=lambda x: sum(1 for c in x[1] if c > 0) / len(x[1]))
    print(f"\n📌 最可能下跌（适合买入）: {WEEKDAY_NAMES[best_buy[0]]} (下跌概率 {sum(1 for c in best_buy[1] if c < 0) / len(best_buy[1]):.0%})")
    print(f"📌 最可能上涨（适合卖出）: {WEEKDAY_NAMES[best_sell[0]]} (上涨概率 {sum(1 for c in best_sell[1] if c > 0) / len(best_sell[1]):.0%})")


# ============================================================
# 7. 分析 5：日间涨跌（星期几→星期几）
# ============================================================

def analyze_day_to_day(records):
    """计算相邻天之间的涨跌（如前一天收盘到当天开盘的跳空）。"""
    daily = {}
    for r in records:
        ds = r["date_str"]
        if ds not in daily:
            daily[ds] = []
        daily[ds].append(r)

    dates = sorted(daily.keys())
    transitions = defaultdict(list)  # (from_wd, to_wd) -> [changes]

    for i in range(1, len(dates)):
        prev_close = daily[dates[i-1]][-1]["usd"]
        cur_open = daily[dates[i]][0]["usd"]
        prev_wd = daily[dates[i-1]][0]["weekday"]
        cur_wd = daily[dates[i]][0]["weekday"]
        gap = (cur_open - prev_close) / prev_close if prev_close else 0
        transitions[(prev_wd, cur_wd)].append(gap)

    print()
    print("=" * 70)
    print("🌙 五、隔夜跳空统计（前日收盘 → 次日开盘）")
    print("=" * 70)
    print(f"{'前日':<6} → {'次日':<6} {'跳空次数':>8} {'平均跳空':>12} {'最大跳空':>12} {'最小跳空':>12}")
    print("-" * 60)

    for (fw, tw), gaps in sorted(transitions.items()):
        print(f"{WEEKDAY_NAMES[fw]:<6} → {WEEKDAY_NAMES[tw]:<6} {len(gaps):>8} {pct(mean(gaps)):>12} {pct(max(gaps)):>12} {pct(min(gaps)):>12}")


# ============================================================
# 8. 分析 6：周度整体走势
# ============================================================

def analyze_weekly_trend(records):
    """按自然周计算周度收益率。"""
    weekly = defaultdict(list)
    for r in records:
        iso = r["datetime"].isocalendar()  # (year, week, weekday)
        week_key = (iso[0], iso[1])
        weekly[week_key].append(r)

    week_returns = []
    print()
    print("=" * 70)
    print("📅 六、周度收益率分布")
    print("=" * 70)

    for (y, w), recs in sorted(weekly.items()):
        if len(recs) < 2:
            continue
        open_p = recs[0]["usd"]
        close_p = recs[-1]["usd"]
        ret = (close_p - open_p) / open_p if open_p else 0
        week_returns.append(ret)

    if week_returns:
        up_weeks = sum(1 for r in week_returns if r > 0)
        down_weeks = sum(1 for r in week_returns if r < 0)
        print(f"  总周数: {len(week_returns)}")
        print(f"  上涨周: {up_weeks} ({up_weeks/len(week_returns):.0%})")
        print(f"  下跌周: {down_weeks} ({down_weeks/len(week_returns):.0%})")
        print(f"  平均周收益率: {pct(mean(week_returns))}")
        print(f"  最大周涨幅: {pct(max(week_returns))}")
        print(f"  最大周跌幅: {pct(min(week_returns))}")


# ============================================================
# 9. 汇总建议
# ============================================================

def print_summary(records):
    """给出简明交易建议。"""
    groups = defaultdict(list)
    for r in records:
        groups[r["weekday"]].append(r)

    daily = defaultdict(list)
    for r in records:
        daily[(r["date_str"], r["weekday"])].append(r)

    wd_avg = {}
    wd_changes = defaultdict(list)
    for (ds, wd), recs in daily.items():
        if not recs:
            continue
        open_p = recs[0]["usd"]
        close_p = recs[-1]["usd"]
        wd_avg[wd] = wd_avg.get(wd, []) + [r["usd"] for r in recs]
        wd_changes[wd].append((close_p - open_p) / open_p if open_p else 0)

    # 综合评分
    print()
    print("=" * 70)
    print("🎯 七、综合建议")
    print("=" * 70)

    # 用均价和涨跌概率综合排序
    scores = {}
    for wd in range(5):  # 仅工作日
        if wd not in wd_avg or wd not in wd_changes:
            continue
        all_prices = wd_avg[wd]
        changes = wd_changes[wd]
        avg_price = mean(all_prices)
        avg_change = mean(changes)
        up_prob = sum(1 for c in changes if c > 0) / len(changes)
        # 买入得分：价格低 + 下跌概率高 → 高分
        buy_score = -avg_price / 100 + (1 - up_prob) * 10
        sell_score = avg_price / 100 + up_prob * 10
        scores[wd] = {
            "avg_price": avg_price,
            "avg_change": avg_change,
            "up_prob": up_prob,
            "buy_score": buy_score,
            "sell_score": sell_score,
        }

    sorted_buy = sorted(scores.items(), key=lambda x: x[1]["buy_score"], reverse=True)
    sorted_sell = sorted(scores.items(), key=lambda x: x[1]["sell_score"], reverse=True)

    print(f"\n  📥 最佳买入日（综合价格低+下跌概率高）:")
    for i, (wd, s) in enumerate(sorted_buy[:3]):
        print(f"     {i+1}. {WEEKDAY_NAMES[wd]} - 均价 {fmt_usd(s['avg_price'])}, 上涨概率 {s['up_prob']:.0%}, 平均日涨跌 {pct(s['avg_change'])}")

    print(f"\n  📤 最佳卖出日（综合价格高+上涨概率高）:")
    for i, (wd, s) in enumerate(sorted_sell[:3]):
        print(f"     {i+1}. {WEEKDAY_NAMES[wd]} - 均价 {fmt_usd(s['avg_price'])}, 上涨概率 {s['up_prob']:.0%}, 平均日涨跌 {pct(s['avg_change'])}")

    # 时段建议
    hour_groups = defaultdict(list)
    for r in records:
        if r["weekday"] < 5:
            hour_groups[r["hour"]].append(r["usd"])

    print(f"\n  ⏰ 日内时段规律（所有工作日聚合）:")
    for h in sorted(hour_groups.keys()):
        prices = hour_groups[h]
        print(f"     {h:02d}:00  均价 {fmt_usd(mean(prices))}  (样本数: {len(prices)})")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="金价周度规律分析")
    parser.add_argument("--csv-dir", default="data", help="CSV 数据目录 (默认: data)")
    parser.add_argument("--plot", action="store_true", help="生成图表 (需 matplotlib)")
    args = parser.parse_args()

    csv_dir = args.csv_dir
    if not os.path.isdir(csv_dir):
        print(f"错误: 目录不存在: {csv_dir}")
        sys.exit(1)

    print("⏳ 加载数据中...")
    records = load_all_data(csv_dir)
    print(f"✅ 加载完成: {len(records)} 条记录")
    print(f"   日期范围: {records[0]['date_str']} ~ {records[-1]['date_str']}")
    print(f"   数据跨度: {(records[-1]['datetime'] - records[0]['datetime']).days} 天")

    # 执行各项分析
    analyze_avg_by_weekday(records)
    analyze_volatility_by_weekday(records)
    analyze_intraday_by_weekday(records)
    analyze_daily_change(records)
    analyze_day_to_day(records)
    analyze_weekly_trend(records)
    print_summary(records)

    # 可选绘图
    if args.plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plot_charts(records)
        except ImportError:
            print("\n⚠️  未安装 matplotlib，跳过图表生成。pip install matplotlib 即可。")

    print("\n✅ 分析完成。")


def plot_charts(records):
    """生成可视化图表。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    # 设置中文字体
    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle("金价周度规律分析", fontsize=16, fontweight="bold")

    # Chart 1: 星期几均价柱状图
    ax1 = axes[0, 0]
    wd_groups = defaultdict(list)
    for r in records:
        wd_groups[r["weekday"]].append(r["usd"])
    wds = list(range(5))  # Mon-Fri
    avgs = [mean(wd_groups[w]) if w in wd_groups else 0 for w in wds]
    bars = ax1.bar([WEEKDAY_NAMES[w] for w in wds], avgs, color=["#3498db", "#2ecc71", "#e74c3c", "#f39c12", "#9b59b6"])
    ax1.set_title("各星期几均价 (USD/盎司)")
    ax1.set_ylabel("USD/盎司")
    for bar, val in zip(bars, avgs):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f"{val:.0f}", ha="center", va="bottom", fontsize=9)

    # Chart 2: 星期几涨跌概率
    ax2 = axes[0, 1]
    daily = defaultdict(list)
    for r in records:
        daily[(r["date_str"], r["weekday"])].append(r)
    wd_probs = {}
    for wd in range(5):
        changes = []
        for (ds, w), recs in daily.items():
            if w == wd and recs:
                open_p = recs[0]["usd"]
                close_p = recs[-1]["usd"]
                changes.append((close_p - open_p) / open_p if open_p else 0)
        if changes:
            up = sum(1 for c in changes if c > 0) / len(changes)
            down = sum(1 for c in changes if c < 0) / len(changes)
            wd_probs[wd] = (up, down)

    wd_list = [w for w in range(5) if w in wd_probs]
    up_vals = [wd_probs[w][0] for w in wd_list]
    down_vals = [wd_probs[w][1] for w in wd_list]
    x_labels = [WEEKDAY_NAMES[w] for w in wd_list]
    x = range(len(wd_list))
    ax2.bar(x, up_vals, label="上涨概率", color="#e74c3c", alpha=0.8)
    ax2.bar(x, down_vals, bottom=up_vals, label="下跌概率", color="#2ecc71", alpha=0.8)
    ax2.set_xticks(x)
    ax2.set_xticklabels(x_labels)
    ax2.set_title("各星期几涨跌概率")
    ax2.set_ylabel("概率")
    ax2.legend()
    ax2.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))

    # Chart 3: 日内小时均价走势
    ax3 = axes[1, 0]
    hour_groups = defaultdict(list)
    for r in records:
        if r["weekday"] < 5:
            hour_groups[r["hour"]].append(r["usd"])
    hours = sorted(hour_groups.keys())
    hour_avgs = [mean(hour_groups[h]) for h in hours]
    ax3.plot(hours, hour_avgs, marker="o", color="#3498db", linewidth=2)
    ax3.set_title("日内小时均价走势（工作日）")
    ax3.set_xlabel("小时")
    ax3.set_ylabel("USD/盎司")
    ax3.grid(True, alpha=0.3)

    # Chart 4: 周度收益率分布
    ax4 = axes[1, 1]
    weekly = defaultdict(list)
    for r in records:
        iso = r["datetime"].isocalendar()
        weekly[(iso[0], iso[1])].append(r)
    week_rets = []
    for (y, w), recs in sorted(weekly.items()):
        if len(recs) >= 2:
            open_p = recs[0]["usd"]
            close_p = recs[-1]["usd"]
            ret = (close_p - open_p) / open_p * 100
            week_rets.append(ret)
    if week_rets:
        ax4.bar(range(len(week_rets)), week_rets, color=["#e74c3c" if r > 0 else "#2ecc71" for r in week_rets])
        ax4.axhline(y=0, color="black", linewidth=0.5)
        ax4.set_title(f"周度收益率 (%)   |   上涨 {sum(1 for r in week_rets if r>0)}/{len(week_rets)} 周")
        ax4.set_xlabel("周序号")
        ax4.set_ylabel("收益率 (%)")
        ax4.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = "weekly_pattern_charts.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"\n📊 图表已保存: {out_path}")
    plt.close()


if __name__ == "__main__":
    main()
