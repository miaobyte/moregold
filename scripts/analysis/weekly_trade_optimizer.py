#!/usr/bin/env python3
"""
每周固定 N 买 N 卖策略优化器
约束：交易时间在每日 9:10 ~ 次日 2:00（银行 App 时段）
方法：枚举所有日+时组合 → 评估 → 组合 N 笔 → 5分钟精细搜索

用法:
    python3 weekly_trade_optimizer.py --trades N [--csv-dir data/] [--top 15]
"""

import os, sys, csv, argparse
from collections import defaultdict
from datetime import datetime
from statistics import mean, stdev
from itertools import combinations, product

USD_COLUMNS = ["金价(USD/盎司)", "金价(USD)"]
WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


# ============================================================
# 1. 加载
# ============================================================

def load_data(csv_dir):
    records = []
    for fname in sorted(os.listdir(csv_dir)):
        if not fname.startswith("gold_") or not fname.endswith(".csv"):
            continue
        with open(os.path.join(csv_dir, fname), "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            usd_col = next((c for c in USD_COLUMNS if c in (reader.fieldnames or [])), None)
            if not usd_col:
                continue
            for row in reader:
                try:
                    usd = float(row[usd_col])
                    dt = datetime.strptime(f"{row['日期'].strip()} {row['时间'].strip()}", "%Y-%m-%d %H:%M:%S")
                    records.append({
                        "dt": dt, "wd": dt.weekday(), "h": dt.hour, "m": dt.minute,
                        "price": usd,
                    })
                except (ValueError, KeyError):
                    continue
    records.sort(key=lambda r: r["dt"])
    return records


def in_window(r):
    h, m = r["h"], r["m"]
    return (h > 9 or (h == 9 and m >= 10)) or h < 2


def build_weekly(records):
    """返回 {week_key: [record]} 仅工作日窗口内，每记录加 label"""
    valid = [r for r in records if in_window(r) and r["wd"] < 5]
    weekly = defaultdict(list)
    for r in valid:
        weekly[r["dt"].isocalendar()[:2]].append(r)
    return {wk: sorted(recs, key=lambda x: x["dt"]) for wk, recs in weekly.items() if len(recs) >= 10}


# ============================================================
# 2. 工具：排序
# ============================================================

def moment_order(wd, h, m=0):
    """凌晨 0-2 点是当天最早时段，直接用日历顺序即可"""
    return wd * 2400 + h * 60 + m


# ============================================================
# 3. 评估单笔交易 (buy_wd, buy_h, buy_m) → (sell_wd, sell_h, sell_m)
# ============================================================

def eval_one_trade(weekly, bw, bh, bm, sw, sh, sm):
    """返回 (avg_return, n_weeks, returns_list)"""
    returns = []
    for wk, series in sorted(weekly.items()):
        buy_p, sell_p = None, None
        buy_dt, sell_dt = None, None
        for s in series:
            if s["wd"] == bw and s["h"] == bh:
                d = abs(s["m"] - bm)
                if buy_p is None or d < abs(buy_dt.minute - bm):
                    buy_p = s["price"]
                    buy_dt = s["dt"]
            if s["wd"] == sw and s["h"] == sh:
                d = abs(s["m"] - sm)
                if sell_p is None or d < abs(sell_dt.minute - sm) if sell_dt else True:
                    sell_p = s["price"]
                    sell_dt = s["dt"]
        if buy_p and sell_p and buy_dt and sell_dt and buy_dt < sell_dt and buy_p > 0:
            returns.append((sell_p - buy_p) / buy_p)
    if len(returns) >= max(3, len(weekly) * 0.5):
        return mean(returns), len(returns), returns
    return None, 0, []


# ============================================================
# 4. 阶段1：枚举所有 1 笔交易的小时组合
# ============================================================

def enumerate_single_trades(weekly):
    """
    以小时为粒度，枚举所有 (buy_wd, buy_h) × (sell_wd, sell_h)。
    买入取 :10 分，卖出取 :50 分。
    返回所有结果，按 avg_return 排序。
    """
    all_hours = list(range(10, 24)) + [0, 1]  # 9:10可用但取整从10开始，0,1是次日凌晨

    results = []
    for bw in range(5):
        for sw in range(bw, 5):
            for bh in all_hours:
                for sh in all_hours:
                    # 排序约束
                    if bw == sw and moment_order(bw, bh) >= moment_order(sw, sh):
                        continue
                    avg_r, n_w, rets = eval_one_trade(weekly, bw, bh, 10, sw, sh, 50)
                    if avg_r is not None:
                        results.append({
                            "buy_wd": bw, "buy_h": bh, "buy_m": 10,
                            "sell_wd": sw, "sell_h": sh, "sell_m": 50,
                            "avg_return": avg_r, "n_weeks": n_w, "returns": rets,
                            "key": (bw, bh, sw, sh),
                        })

    results.sort(key=lambda x: -x["avg_return"])
    return results


# ============================================================
# 5. 阶段2：从 top 1-trade 策略组合出 N-trade 策略
# ============================================================

def combine_n_trades(single_results, N, top_k=200):
    """
    多样化组合：按 (buy_wd, sell_wd) 分组，每组取 top 5，再从各组组合 N 笔。
    约束: sell_i < buy_{i+1}
    """
    # 按 (buy_wd, sell_wd) 分组，每组取 top 5
    groups = defaultdict(list)
    for r in single_results:
        gkey = (r["buy_wd"], r["sell_wd"])
        if len(groups[gkey]) < 5:
            groups[gkey].append(r)

    # 收集所有候选
    candidates = []
    for r in single_results[:top_k]:
        bo = moment_order(r["buy_wd"], r["buy_h"], r["buy_m"])
        so = moment_order(r["sell_wd"], r["sell_h"], r["sell_m"])
        candidates.append({**r, "buy_order": bo, "sell_order": so})

    # 去重
    seen_keys = set()
    unique_candidates = []
    for c in candidates:
        if c["key"] not in seen_keys:
            seen_keys.add(c["key"])
            unique_candidates.append(c)

    print(f"   候选 1 笔交易: {len(unique_candidates)} 个 (来自 {len(groups)} 个日组合)")

    # 生成 N 组合
    all_combos = []
    for combo in combinations(unique_candidates, N):
        sorted_combo = sorted(combo, key=lambda x: x["buy_order"])
        valid = True
        for i in range(N - 1):
            if sorted_combo[i]["sell_order"] >= sorted_combo[i + 1]["buy_order"]:
                valid = False
                break
        if valid:
            all_combos.append(sorted_combo)

    # 去重
    seen = set()
    unique = []
    for c in all_combos:
        k = tuple(r["key"] for r in c)
        if k not in seen:
            seen.add(k)
            unique.append(c)

    return unique


# ============================================================
# 6. 评估 N 笔策略
# ============================================================

def eval_n_trades(weekly, schedule):
    """
    schedule: [(bw, bh, bm, sw, sh, sm), ...] 长度 N
    返回 {avg_return, n_weeks, returns, trade_rets, win_rate, max_r, min_r, std_r}
    """
    N = len(schedule)
    all_returns = []
    trade_rets = [[] for _ in range(N)]

    for wk, series in sorted(weekly.items()):
        used = set()
        executed = []

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
            trade_rets[ti].append(ret)
            used.add(best_b[0])
            used.add(best_s[0])

        if len(executed) == N:
            all_returns.append(sum(executed))

    if len(all_returns) < max(3, len(weekly) * 0.4):
        return None

    return {
        "avg_return": mean(all_returns),
        "n_weeks": len(all_returns),
        "returns": all_returns,
        "trade_rets": trade_rets,
        "win_rate": sum(1 for r in all_returns if r > 0) / len(all_returns),
        "max_r": max(all_returns), "min_r": min(all_returns),
        "std_r": stdev(all_returns) if len(all_returns) >= 2 else 0,
    }


# ============================================================
# 7. 阶段3：5分钟精细搜索
# ============================================================

def refine_5min(weekly, best_hour_results, N, top_n=20):
    """对 top N 小时结果，在 ±30 分钟内做 5 分钟搜索"""
    fine = []
    for hr in best_hour_results[:top_n]:
        sched = hr["schedule"]  # [(bw,bh,bm,sw,sh,sm), ...]

        # 每笔生成候选分钟
        opts_per_trade = []
        for (bw, bh, bm, sw, sh, sm) in sched:
            bo = []
            for m2 in range(max(0, bm - 30), min(55, bm + 30) + 1, 5):
                bo.append((bw, bh, m2))
            so = []
            for m2 in range(max(0, sm - 30), min(55, sm + 30) + 1, 5):
                so.append((sw, sh, m2))
            opts_per_trade.append((bo, so))

        # 组合
        combos = []
        for picks in product(*[product(bo, so) for bo, so in opts_per_trade]):
            sched2 = []
            valid = True
            last_ord = -1
            for (bw, bh, bm2), (sw, sh, sm2) in picks:
                bo2 = moment_order(bw, bh, bm2)
                so2 = moment_order(sw, sh, sm2)
                if bo2 >= so2 or bo2 <= last_ord:
                    valid = False
                    break
                last_ord = so2
                sched2.append((bw, bh, bm2, sw, sh, sm2))
            if valid:
                combos.append(sched2)

        # 去重 + 评估
        seen = set()
        for s2 in combos:
            k = tuple(s2)
            if k in seen:
                continue
            seen.add(k)
            r = eval_n_trades(weekly, s2)
            if r:
                fine.append({"schedule": s2, **r})

    fine.sort(key=lambda x: -x["avg_return"])
    return fine


# ============================================================
# 8. 输出
# ============================================================

def print_single_trade_top(single_results, top_n=10):
    print()
    print("=" * 80)
    print(f"📊 1笔交易 — Top {top_n} 小时级策略")
    print("=" * 80)
    print(f"  {'#':<3} {'买入':<12} {'卖出':<12} {'周均':>8} {'胜率':>6} {'周数':>5} {'最大':>8} {'最小':>8}")
    print("  " + "-" * 63)
    for i, r in enumerate(single_results[:top_n]):
        w = sum(1 for x in r["returns"] if x > 0) / len(r["returns"])
        print(f"  {i+1:<3} {WEEKDAY_NAMES[r['buy_wd']]} {r['buy_h']:02d}:{r['buy_m']:02d}  "
              f"{WEEKDAY_NAMES[r['sell_wd']]} {r['sell_h']:02d}:{r['sell_m']:02d}  "
              f"{r['avg_return']*100:>+7.2f}% {w:>5.0%} {r['n_weeks']:>5} "
              f"{max(r['returns'])*100:>+7.2f}% {min(r['returns'])*100:>+7.2f}%")


def print_n_trade_results(results, N, top_n=15):
    print()
    print("=" * 80)
    print(f"🏆 {N}买{N}卖固定策略 Top {min(top_n, len(results))}")
    print("=" * 80)

    if not results:
        print("  无有效策略")
        return

    # Header
    hdr = f"  {'#':<3}"
    for ti in range(N):
        hdr += f" {'买'+str(ti+1):<14} {'卖'+str(ti+1):<14}"
    hdr += f" {'周均':>8} {'胜率':>6} {'周':>4} {'最大':>8} {'最小':>8} {'std':>8}"
    print(hdr)
    print("  " + "-" * (8 + N * 28 + 42))

    for rank, r in enumerate(results[:top_n]):
        line = f"  {rank+1:<3}"
        for ti in range(N):
            if ti < len(r["schedule"]):
                bw, bh, bm, sw, sh, sm = r["schedule"][ti]
                line += f" {WEEKDAY_NAMES[bw]} {bh:02d}:{bm:02d}  {WEEKDAY_NAMES[sw]} {sh:02d}:{sm:02d}"
            else:
                line += f" {'—':<14} {'—':<14}"
        line += (f" {r['avg_return']*100:>+7.2f}% {r['win_rate']:>5.0%} "
                 f"{r['n_weeks']:>4} {r['max_r']*100:>+7.2f}% {r['min_r']*100:>+7.2f}% "
                 f"{r['std_r']*100:>7.2f}%")
        print(line)

    # 最优策略详情
    best = results[0]
    print(f"\n  📌 最优策略详情:")
    for ti in range(N):
        bw, bh, bm, sw, sh, sm = best["schedule"][ti]
        tr = best["trade_rets"][ti]
        atr = mean(tr)
        wr = sum(1 for x in tr if x > 0) / len(tr)
        print(f"     交易{ti+1}: {WEEKDAY_NAMES[bw]} {bh:02d}:{bm:02d} → "
              f"{WEEKDAY_NAMES[sw]} {sh:02d}:{sm:02d}  "
              f"(均值 {atr*100:+.2f}%, 胜率 {wr:.0%})")
    print(f"     ─────────────────────────────")
    print(f"     周均总收益: {best['avg_return']*100:+.2f}%")
    print(f"     胜率: {best['win_rate']:.0%}  标准差: {best['std_r']*100:.2f}%")
    print(f"     覆盖 {best['n_weeks']} 周")

    # 每周明细
    print(f"\n  📋 每周收益明细:")
    line = f"  {'周':<4}"
    for ti in range(N):
        line += f" {'T'+str(ti+1):>8}"
    line += f" {'合计':>8}"
    print(line)
    print("  " + "-" * (8 + N * 9 + 8))
    for wi in range(best["n_weeks"]):
        line = f"  {wi+1:<4}"
        total = 0
        for ti in range(N):
            v = best["trade_rets"][ti][wi]
            total += v
            line += f" {v*100:>+7.2f}%"
        line += f" {total*100:>+7.2f}%"
        print(line)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="每周固定 N 买 N 卖策略优化器")
    parser.add_argument("--csv-dir", default="data")
    parser.add_argument("--trades", type=int, default=2, help="每周交易次数")
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()

    N = args.trades
    csv_dir = args.csv_dir

    if not os.path.isdir(csv_dir):
        print(f"错误: 目录不存在: {csv_dir}")
        sys.exit(1)

    print("⏳ 加载数据...")
    records = load_data(csv_dir)
    in_w = sum(1 for r in records if in_window(r) and r["wd"] < 5)
    print(f"✅ {len(records)} 条, 窗口内工作日 {in_w} 条")

    weekly = build_weekly(records)
    print(f"   完整交易周: {len(weekly)} 周")

    # 阶段1: 枚举所有 1 笔策略
    print(f"\n🔍 阶段1: 枚举所有 1 笔交易（日+时组合）...")
    single_results = enumerate_single_trades(weekly)
    print(f"   有效 1 笔策略: {len(single_results)} 个")

    print_single_trade_top(single_results, top_n=10)

    if N == 1:
        # 直接精细搜索
        hour_results = [{"schedule": [
            (r["buy_wd"], r["buy_h"], r["buy_m"], r["sell_wd"], r["sell_h"], r["sell_m"])
        ]} for r in single_results[:20]]
        fine = refine_5min(weekly, hour_results, 1, top_n=20)
        print_n_trade_results(fine, 1, args.top)
    else:
        # 阶段2: 组合 N 笔
        print(f"\n🔗 阶段2: 从 top 1笔策略组合出 {N}笔策略...")
        combos = combine_n_trades(single_results, N, top_k=min(300, len(single_results)))
        print(f"   不重叠组合数: {len(combos)} 个")

        # 评估每个组合
        print(f"   评估中...")
        hour_results = []
        for c in combos:
            sched = [(r["buy_wd"], r["buy_h"], r["buy_m"], r["sell_wd"], r["sell_h"], r["sell_m"]) for r in c]
            r = eval_n_trades(weekly, sched)
            if r:
                hour_results.append({"schedule": sched, **r})
        hour_results.sort(key=lambda x: -x["avg_return"])

        # 阶段3: 精细
        print(f"🔬 阶段3: 5分钟精细搜索...")
        fine = refine_5min(weekly, hour_results, N, top_n=min(15, len(hour_results)))
        print_n_trade_results(fine, N, args.top)

        # 对比
        if fine and single_results:
            best_1 = single_results[0]["avg_return"]
            best_n = fine[0]["avg_return"]
            print(f"\n📊 对比: 1笔最优 {best_1*100:+.2f}% → {N}笔最优 {best_n*100:+.2f}% "
                  f"(增量 {(best_n-best_1)*100:+.2f}%)")

    print("\n✅ 完成。")


if __name__ == "__main__":
    main()
