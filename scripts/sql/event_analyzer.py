#!/usr/bin/env python3
"""
金价波动事件事后分析器

用法:
    python3 scripts/sql/event_analyzer.py --date 2026-06-22       # 分析某一天
    python3 scripts/sql/event_analyzer.py --week 202625           # 分析某一周
    python3 scripts/sql/event_analyzer.py --date $(date -v-1d +%F)  # 分析昨天
    python3 scripts/sql/event_analyzer.py --week $(date +%Y%U)    # 分析本周

流程:
  1. 从 gold_prices 提取时间段内的价格数据
  2. 用滑动窗口检测急涨/急跌/跳空/突破/反转
  3. 写入 gold_event 表 (source='AUTO')
  4. 输出检测到的事件摘要
"""

import sys, os, argparse
import mysql.connector
from datetime import datetime, timedelta
from collections import defaultdict

# ---- 远程 DB (从环境变量 GOLD_DB_URL 读取) ----
def _db_config():
    from urllib.parse import urlparse
    url = os.environ.get("GOLD_DB_URL", "")
    if not url:
        raise RuntimeError("未设置 GOLD_DB_URL 环境变量")
    u = urlparse(url)
    return {
        "host": u.hostname,
        "port": u.port or 3306,
        "user": u.username,
        "password": u.password,
        "database": u.path.lstrip("/"),
        "charset": "utf8mb4",
    }

# ============================================================
# 建表 (幂等)
# ============================================================

EVENT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS gold_event (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    start_dt      DATETIME     NOT NULL COMMENT '事件起始',
    end_dt        DATETIME     NOT NULL COMMENT '事件结束',
    start_price   DOUBLE       NOT NULL,
    end_price     DOUBLE       NOT NULL,
    change_pct    DOUBLE       NOT NULL COMMENT '涨跌幅%',
    peak_price    DOUBLE       DEFAULT NULL,
    valley_price  DOUBLE       DEFAULT NULL,
    event_type    VARCHAR(32)  NOT NULL,
    direction     ENUM('UP','DOWN','SHAKE') NOT NULL,
    severity      TINYINT      NOT NULL COMMENT '1-5',
    cause_cat     VARCHAR(64)  DEFAULT NULL,
    cause_detail  VARCHAR(512) DEFAULT NULL,
    news_url      VARCHAR(1024) DEFAULT NULL,
    related_event VARCHAR(128) DEFAULT NULL,
    rsi14         DOUBLE       DEFAULT NULL,
    atr14         DOUBLE       DEFAULT NULL,
    sma20         DOUBLE       DEFAULT NULL,
    tags          VARCHAR(256) DEFAULT NULL,
    notes         TEXT         DEFAULT NULL,
    source        ENUM('AUTO','MANUAL') NOT NULL DEFAULT 'AUTO',
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_time (start_dt),
    INDEX idx_type (event_type),
    INDEX idx_direction (direction),
    INDEX idx_severity (severity),
    INDEX idx_cause (cause_cat)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='金价波动事件表';
"""

# ============================================================
# 数据加载
# ============================================================

class PriceSeries:
    def __init__(self, rows):
        """rows: [(dt, price_usd), ...]"""
        self.data = sorted(rows, key=lambda x: x[0])
        self._prices = [r[1] for r in self.data]
        self._dts = [r[0] for r in self.data]

    def __len__(self): return len(self.data)

    def window(self, i, minutes):
        """从索引 i 开始，往后取 minutes 分钟内的数据"""
        start = self._dts[i]
        end = start + timedelta(minutes=minutes)
        seg = [(self._dts[j], self._prices[j])
               for j in range(i, len(self.data))
               if self._dts[j] <= end]
        return seg

    def sma(self, i, n):
        """索引 i 处的 n 期 SMA"""
        if i < n - 1:
            return None
        return sum(self._prices[i - n + 1:i + 1]) / n


def load_prices(cursor, start, end):
    cursor.execute("""
        SELECT dt, price_usd FROM gold_prices
        WHERE dt >= %s AND dt < %s
        ORDER BY dt
    """, (start, end))
    return PriceSeries(cursor.fetchall())


# ============================================================
# 事件检测
# ============================================================

def detect_surge_plunge(series, window_min=60, threshold_pct=0.8):
    """滑动窗口检测急涨急跌。"""
    events = []
    for i in range(len(series)):
        win = series.window(i, window_min)
        if len(win) < 2:
            continue
        p_start, p_end = win[0][1], win[-1][1]
        change = (p_end - p_start) / p_start * 100
        if abs(change) < threshold_pct:
            continue

        direction = 'UP' if change > 0 else 'DOWN'
        etype = 'SURGE' if change > 0 else 'PLUNGE'
        sev = min(5, max(1, int(abs(change) / 0.5) + 1))

        events.append({
            "start_dt": win[0][0],
            "end_dt": win[-1][0],
            "start_price": p_start,
            "end_price": p_end,
            "change_pct": round(change, 4),
            "event_type": etype,
            "direction": direction,
            "severity": sev,
        })

    # 合并重叠事件（保留涨跌幅最大的）
    return _merge_overlapping(events)


def detect_gaps(prices_by_date):
    """检测隔夜跳空。prices_by_date: {date: PriceSeries}"""
    events = []
    dates = sorted(prices_by_date.keys())
    for i in range(1, len(dates)):
        prev = prices_by_date[dates[i - 1]]
        curr = prices_by_date[dates[i]]
        if len(prev) == 0 or len(curr) == 0:
            continue
        p_close = prev._prices[-1]
        p_open = curr._prices[0]
        gap_pct = (p_open - p_close) / p_close * 100
        if abs(gap_pct) < 0.3:
            continue

        direction = 'UP' if gap_pct > 0 else 'DOWN'
        events.append({
            "start_dt": prev._dts[-1],
            "end_dt": curr._dts[0],
            "start_price": p_close,
            "end_price": p_open,
            "change_pct": round(gap_pct, 4),
            "event_type": "GAP",
            "direction": direction,
            "severity": min(5, max(1, int(abs(gap_pct) / 0.3) + 1)),
        })
    return events


def detect_reversal(series):
    """检测均线交叉 (SMA5 vs SMA20)，至少间隔 60 分钟。"""
    events = []
    sma5_prev, sma20_prev = None, None
    last_cross_dt = None
    for i in range(len(series)):
        sma5 = series.sma(i, 5)
        sma20 = series.sma(i, 20)
        if sma5 is None or sma20 is None:
            sma5_prev, sma20_prev = sma5, sma20
            continue
        if sma5_prev is None or sma20_prev is None:
            sma5_prev, sma20_prev = sma5, sma20
            continue

        # 过滤微交叉: 价格漂移 <0.2% 时不算有效
        cross_magnitude = abs(sma5 - sma20) / sma20
        is_valid = cross_magnitude > 0.001  # 差值 >0.1%
        is_fresh = last_cross_dt is None or (series._dts[i] - last_cross_dt).total_seconds() > 3600

        # 金叉
        if sma5_prev <= sma20_prev and sma5 > sma20 and is_valid and is_fresh:
            events.append({
                "start_dt": series._dts[i], "end_dt": series._dts[i],
                "start_price": series._prices[i], "end_price": series._prices[i],
                "change_pct": round(cross_magnitude * 100, 4),
                "peak_price": series._prices[i], "valley_price": series._prices[i],
                "event_type": "GOLDEN_CROSS", "direction": "UP", "severity": 2,
            })
            last_cross_dt = series._dts[i]
        # 死叉
        elif sma5_prev >= sma20_prev and sma5 < sma20 and is_valid and is_fresh:
            events.append({
                "start_dt": series._dts[i], "end_dt": series._dts[i],
                "start_price": series._prices[i], "end_price": series._prices[i],
                "change_pct": round(-cross_magnitude * 100, 4),
                "peak_price": series._prices[i], "valley_price": series._prices[i],
                "event_type": "DEATH_CROSS", "direction": "DOWN", "severity": 2,
            })
            last_cross_dt = series._dts[i]
        sma5_prev, sma20_prev = sma5, sma20
    return events


def _merge_overlapping(events):
    """合并时间重叠的事件，保留变化最大的。"""
    if len(events) < 2:
        return events
    events.sort(key=lambda x: x["start_dt"])
    merged, pending = [], [events[0]]
    for e in events[1:]:
        if e["start_dt"] <= pending[-1]["end_dt"]:
            pending.append(e)
        else:
            best = max(pending, key=lambda x: abs(x["change_pct"]))
            merged.append(best)
            pending = [e]
    if pending:
        merged.append(max(pending, key=lambda x: abs(x["change_pct"])))
    return merged


# ============================================================
# 写入
# ============================================================

def insert_events(cursor, events):
    """批量写入事件。先删同时间范围的旧AUTO事件，再插入新数据。"""
    if not events:
        return 0

    dmin = min(e["start_dt"] for e in events)
    dmax = max(e["end_dt"] for e in events)
    cursor.execute(
        "DELETE FROM gold_event WHERE source='AUTO' AND start_dt >= %s AND end_dt <= %s",
        (dmin, dmax)
    )

    sql = """
        INSERT INTO gold_event
            (start_dt, end_dt, start_price, end_price, change_pct,
             event_type, direction, severity)
        VALUES (%(start_dt)s, %(end_dt)s, %(start_price)s, %(end_price)s,
                %(change_pct)s, %(event_type)s, %(direction)s, %(severity)s)
    """
    cursor.executemany(sql, events)
    return cursor.rowcount


# ============================================================
# 输出
# ============================================================

def print_events(cursor, start, end):
    cursor.execute("""
        SELECT id, start_dt, end_dt, ROUND(change_pct,2),
               event_type, direction, severity,
               COALESCE(cause_cat,'AUTO') AS cause_cat,
               COALESCE(cause_detail,'(待标注)') AS cause_detail
        FROM gold_event
        WHERE start_dt >= %s AND end_dt <= %s
        ORDER BY ABS(change_pct) DESC
    """, (start, end))
    rows = cursor.fetchall()
    if not rows:
        print("  (无事件)")
        return

    print(f"\n  {'id':<6} {'时间':<22} {'类型':<14} {'方向':<6} {'涨跌':>8} {'严重':>4} {'原因':<20} {'详情'}")
    print("  " + "-" * 100)
    for r in rows:
        dt_range = f"{str(r[1])[5:16]} ~ {str(r[2])[11:16]}"
        print(f"  {r[0]:<6} {dt_range:<22} {r[4]:<14} {r[5]:<6} {r[3]:>+7.2f}% {r[6]:>4}  {r[7]:<20} {r[8][:30]}")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="金价事件事后分析器")
    parser.add_argument("--date", help="分析日期 YYYY-MM-DD")
    parser.add_argument("--week", help="分析周 YYYYWW")
    parser.add_argument("--from", dest="from_date", help="起始日期")
    parser.add_argument("--to", dest="to_date", help="结束日期")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅检测不写入")
    args = parser.parse_args()

    # 确定时间范围
    if args.date:
        start = datetime.strptime(args.date, "%Y-%m-%d")
        end = start + timedelta(days=1)
        day_range = True
    elif args.week:
        y, w = int(args.week[:4]), int(args.week[4:])
        start = datetime.strptime(f"{y}-W{w:02d}-1", "%G-W%V-%u")
        end = start + timedelta(days=5)
        day_range = False
    elif args.from_date:
        start = datetime.strptime(args.from_date, "%Y-%m-%d")
        end = datetime.strptime(args.to_date, "%Y-%m-%d") + timedelta(days=1) if args.to_date else start + timedelta(days=1)
        day_range = (end - start).days <= 2
    else:
        start = datetime.now().replace(hour=0, minute=0, second=0) - timedelta(days=1)
        end = start + timedelta(days=1)
        day_range = True

    print(f"🔍 分析范围: {start} ~ {end}")

    conn = mysql.connector.connect(**_db_config())
    cur = conn.cursor()
    cur.execute("SET SESSION group_concat_max_len = 1000000")

    # 检查表是否存在
    cur.execute("SHOW TABLES LIKE 'gold_event'")
    if not cur.fetchone():
        print("❌ gold_event 表不存在，请先执行 event_analyzer.py 中的建表 SQL")
        print("   (建表语句在脚本顶部的 EVENT_TABLE_DDL 变量中)")
        cur.close()
        conn.close()
        return

    all_events = []

    # 1. 按天加载数据（保留日期分组用于跳空检测）
    prices_by_date = {}
    if day_range:
        # 加前后各一天用于跳空检测
        extended_start = start - timedelta(days=1)
        extended_end = end + timedelta(days=1)
    else:
        extended_start = start
        extended_end = end

    cursor2 = conn.cursor()
    while extended_start < extended_end:
        day_end = extended_start + timedelta(days=1)
        series = load_prices(cursor2, extended_start, day_end)
        if len(series) > 0:
            prices_by_date[extended_start.date()] = series
        extended_start = day_end

    # 2. 每日检测急涨急跌
    for d, series in prices_by_date.items():
        events = detect_surge_plunge(series, window_min=60, threshold_pct=0.6)
        all_events.extend(events)

    # 3. 隔夜跳空
    events = detect_gaps(prices_by_date)
    all_events.extend(events)

    print(f"\n📊 检测到 {len(all_events)} 个事件")

    # 按类型分类统计
    by_type = defaultdict(list)
    for e in all_events:
        by_type[e["event_type"]].append(e)

    for etype in ["SURGE", "PLUNGE", "GAP"]:
        if by_type[etype]:
            changes = [abs(e["change_pct"]) for e in by_type[etype]]
            print(f"  {etype:<14} {len(by_type[etype]):>3} 个  "
                  f"均值 {sum(changes)/len(changes):.2f}%  最大 {max(changes):.2f}%")

    # 4. 写入
    if all_events and not args.dry_run:
        n = insert_events(cur, all_events)
        conn.commit()
        print(f"\n✅ 已写入 {n} 条事件到 gold_event")

    # 5. 输出
    print_events(cur, start, end)

    cur.close()
    conn.close()
    print(f"\n✅ 分析完成。")


if __name__ == "__main__":
    main()
