#!/usr/bin/env python3
"""
CSV → MySQL 导入与增量同步脚本 (v2)

同步策略:
  1. 首次运行（表为空）         → 自动全量导入
  2. --full 强制                → 清空表 + 全量导入
  3. 增量同步（默认）:
     a. 对比 CSV 和 MySQL 中每个日期的记录数
     b. 新增日期                → 全部导入
     c. 记录数不一致的旧日期    → 先删后插（确保完整）
     d. 记录数一致的日期        → 跳过
  4. 最终校验                   → 确认 CSV 与 MySQL 总记录数一致

用法:
    python3 scripts/sql/import_to_mysql.py [--csv-dir data] [--full] [--dry-run]
"""

import os
import sys
import csv
import argparse
import mysql.connector
from datetime import datetime
from collections import defaultdict

# ============================================================
# 配置
# ============================================================

DB_CONFIG = {
    "host": "localhost",
    "user": "gold",
    "password": "gold123",
    "database": "gold_db",
    "charset": "utf8mb4",
    "allow_local_infile": True,
}

USD_COLS = ["金价(USD/盎司)", "金价(USD)"]
CNY_COLS = ["金价(CNY/克)", "金价(CNY)"]

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS gold_prices (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date  DATE        NOT NULL,
    trade_time  TIME        NOT NULL,
    price_usd   DOUBLE      NOT NULL,
    price_cny   DOUBLE      NOT NULL,
    weekday     TINYINT     NOT NULL COMMENT '0=Mon..6=Sun',
    hour        TINYINT     NOT NULL,
    minute      TINYINT     NOT NULL,
    dt          DATETIME    NOT NULL,
    year_week   INT         NOT NULL COMMENT 'YYYYWW format',
    UNIQUE KEY uk_datetime (trade_date, trade_time),
    INDEX idx_weekday_hour (weekday, hour),
    INDEX idx_year_week (year_week),
    INDEX idx_dt (dt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

# ============================================================
# 工具
# ============================================================

def get_connection():
    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SET SESSION group_concat_max_len = 1000000")
    cur.close()
    return conn


def ensure_table(cursor):
    """确保表存在。"""
    cursor.execute(TABLE_DDL)


# ============================================================
# CSV 解析
# ============================================================

def parse_csv_files(csv_dir):
    """解析所有 CSV 文件，自动去重（按 trade_date + trade_time 唯一）。

    返回:
        records:     去重后的记录列表
        date_counts: {date_str: record_count}
        dup_count:   被去重的记录数
    """
    seen = {}  # (date, time) -> record dict, 用于去重
    dup_count = 0
    file_counts = []

    files = sorted(
        f for f in os.listdir(csv_dir)
        if f.startswith("gold_") and f.endswith(".csv")
    )

    if not files:
        print("❌ 未找到 CSV 文件！")
        sys.exit(1)

    print(f"📂 发现 {len(files)} 个 CSV 文件")
    for fname in files:
        fpath = os.path.join(csv_dir, fname)
        file_count = 0
        file_dup = 0
        with open(fpath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            usd_col = next((c for c in USD_COLS if c in fieldnames), None)
            cny_col = next((c for c in CNY_COLS if c in fieldnames), None)
            if not usd_col:
                print(f"  ⚠️  跳过 {fname}: 找不到价格列 (可用: {fieldnames})")
                continue

            for row in reader:
                try:
                    date_str = row["日期"].strip()
                    time_str = row["时间"].strip()
                    usd = float(row[usd_col])
                    cny = float(row[cny_col]) if cny_col else 0.0
                except (ValueError, KeyError):
                    continue

                dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
                key = (date_str, time_str)

                rec = {
                    "trade_date": date_str,
                    "trade_time": time_str,
                    "price_usd": usd,
                    "price_cny": cny,
                    "weekday": dt.weekday(),
                    "hour": dt.hour,
                    "minute": dt.minute,
                    "dt": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "year_week": int(dt.strftime("%Y%U")),
                }

                if key in seen:
                    file_dup += 1
                    # 保留最新的（后出现的覆盖先出现的）
                    seen[key] = rec
                else:
                    seen[key] = rec

                file_count += 1

        dup_info = f", 去重 {file_dup}" if file_dup else ""
        print(f"  ✅ {fname}: {file_count} 条{dup_info}")
        file_counts.append((fname, file_count, file_dup))
        dup_count += file_dup

    # 从去重后的 seen 构建 records 和 date_counts
    records = list(seen.values())
    records.sort(key=lambda r: (r["trade_date"], r["trade_time"]))

    date_counts = defaultdict(int)
    for r in records:
        date_counts[r["trade_date"]] += 1

    if dup_count:
        print(f"\n  ⚠️  共去重 {dup_count} 条重复记录（保留最新值）")

    return records, dict(date_counts), dup_count


# ============================================================
# MySQL 查询
# ============================================================

def get_mysql_date_counts(cursor):
    """返回 MySQL 中每个日期的记录数: {date_str: count}。"""
    cursor.execute("""
        SELECT trade_date, COUNT(*)
        FROM gold_prices
        GROUP BY trade_date
    """)
    return {str(row[0]): row[1] for row in cursor.fetchall()}


def get_mysql_table_status(cursor):
    """返回 MySQL 表状态: (total_rows, min_date, max_date)。"""
    cursor.execute("""
        SELECT COUNT(*),
               COALESCE(MIN(trade_date), 'N/A'),
               COALESCE(MAX(trade_date), 'N/A')
        FROM gold_prices
    """)
    return cursor.fetchone()


def delete_dates(cursor, dates):
    """删除指定日期的所有记录。"""
    if not dates:
        return 0
    placeholders = ", ".join(["%s"] * len(dates))
    sql = f"DELETE FROM gold_prices WHERE trade_date IN ({placeholders})"
    cursor.execute(sql, list(dates))
    return cursor.rowcount


def batch_insert(cursor, records, batch_size=5000):
    """批量插入记录，返回插入行数。"""
    if not records:
        return 0
    sql = """
        INSERT INTO gold_prices
            (trade_date, trade_time, price_usd, price_cny,
             weekday, hour, minute, dt, year_week)
        VALUES (%(trade_date)s, %(trade_time)s, %(price_usd)s, %(price_cny)s,
                %(weekday)s, %(hour)s, %(minute)s, %(dt)s, %(year_week)s)
    """
    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        cursor.executemany(sql, batch)
    return total


# ============================================================
# 核心同步逻辑
# ============================================================

def compute_sync_plan(csv_date_counts, mysql_date_counts):
    """对比 CSV 和 MySQL，生成同步计划。

    返回:
        new_dates:    CSV 有但 MySQL 没有的日期集合  → 需要全量导入
        stale_dates: 两边都有但记录数不一致的日期集合 → 需要删后重导
        skip_dates:  两边一致，无需操作的日期集合
        extra_dates: MySQL 有但 CSV 没有的日期集合    → 需要删除（异常情况）
    """
    csv_dates = set(csv_date_counts.keys())
    mysql_dates = set(mysql_date_counts.keys())

    new_dates = csv_dates - mysql_dates
    extra_dates = mysql_dates - csv_dates

    # 两边都有的日期，比较记录数
    stale_dates = set()
    skip_dates = set()
    for d in csv_dates & mysql_dates:
        if csv_date_counts[d] != mysql_date_counts[d]:
            stale_dates.add(d)
        else:
            skip_dates.add(d)

    return new_dates, stale_dates, skip_dates, extra_dates


def execute_sync(conn, cursor, records, csv_date_counts, mysql_date_counts, sync_plan, dry_run=False):
    """执行同步计划。"""
    new_dates, stale_dates, skip_dates, extra_dates = sync_plan

    # 1. 删除 CSV 中已不存在的日期（异常恢复）
    if extra_dates:
        print(f"\n  ⚠️  MySQL 中有 {len(extra_dates)} 个日期不在 CSV 中:")
        for d in sorted(extra_dates)[:5]:
            print(f"     - {d} ({mysql_date_counts.get(d, '?')} 条)")
        if len(extra_dates) > 5:
            print(f"     ... 等共 {len(extra_dates)} 个")
        if not dry_run:
            deleted = delete_dates(cursor, extra_dates)
            print(f"  🗑️  已删除 {deleted} 条孤立记录")
        else:
            print(f"  [DRY-RUN] 将删除这些日期的记录")

    # 2. 对需要更新的旧日期：先删后插
    if stale_dates:
        dates_to_refresh = stale_dates
        print(f"\n  🔄 需要刷新的旧日期: {len(dates_to_refresh)} 个")
        for d in sorted(dates_to_refresh)[:5]:
            print(f"     - {d}: CSV={csv_date_counts[d]}条, MySQL={mysql_date_counts.get(d, 0)}条")
        if len(dates_to_refresh) > 5:
            print(f"     ... 等共 {len(dates_to_refresh)} 个")

        if not dry_run:
            deleted = delete_dates(cursor, dates_to_refresh)
            print(f"  🗑️  已删除 {deleted} 条旧记录")
            conn.commit()

    # 3. 收集需要导入的记录：新日期 + 需刷新的旧日期
    dates_to_import = new_dates | stale_dates
    if dates_to_import:
        to_insert = [r for r in records if r["trade_date"] in dates_to_import]
        print(f"\n  📥 待导入: {len(dates_to_import)} 个日期, {len(to_insert)} 条记录")

        if not dry_run:
            inserted = batch_insert(cursor, to_insert)
            conn.commit()
            print(f"  ✅ 已导入 {inserted} 条")
        else:
            print(f"  [DRY-RUN] 将导入这些记录")

    # 4. 跳过的日期
    if skip_dates:
        total_skip_rows = sum(mysql_date_counts[d] for d in skip_dates)
        print(f"\n  ⏭️  已同步（跳过）: {len(skip_dates)} 个日期, {total_skip_rows} 条记录")


# ============================================================
# 校验
# ============================================================

def verify(conn, cursor, csv_date_counts):
    """同步后校验：对比 CSV 和 MySQL 的总记录数。"""
    mysql_total = get_mysql_table_status(cursor)[0]
    csv_total = sum(csv_date_counts.values())

    # 逐日期抽查
    mysql_counts = get_mysql_date_counts(cursor)
    mismatches = []
    for d in csv_date_counts:
        if d not in mysql_counts:
            mismatches.append((d, csv_date_counts[d], 0, "缺失"))
        elif csv_date_counts[d] != mysql_counts[d]:
            mismatches.append((d, csv_date_counts[d], mysql_counts[d], "不一致"))

    if mismatches:
        print(f"\n  ❌ 校验失败！{len(mismatches)} 个日期数据不一致:")
        for d, csv_c, mysql_c, reason in mismatches[:10]:
            print(f"     {d}: CSV={csv_c}, MySQL={mysql_c} ({reason})")
    else:
        print(f"\n  ✅ 校验通过: MySQL 共 {mysql_total} 条 = CSV 共 {csv_total} 条")
        print(f"     覆盖 {len(csv_date_counts)} 个日期, 全部一致")

    return len(mismatches) == 0


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="CSV → MySQL 同步 (v2)")
    parser.add_argument("--csv-dir", default="data", help="CSV 数据目录")
    parser.add_argument("--full", action="store_true", help="强制全量重新导入（清空表）")
    parser.add_argument("--dry-run", action="store_true", help="仅分析差异，不实际执行")
    args = parser.parse_args()

    csv_dir = args.csv_dir
    if not os.path.isdir(csv_dir):
        print(f"❌ 目录不存在: {csv_dir}")
        sys.exit(1)

    # ---- 解析 CSV ----
    print("=" * 60)
    print("📂 解析 CSV 文件...")
    print("=" * 60)
    records, csv_date_counts, dup_count = parse_csv_files(csv_dir)
    print(f"\n📊 CSV 合计: {len(records)} 条, {len(csv_date_counts)} 个日期"
          + (f" (去重 {dup_count} 条)" if dup_count else ""))

    # ---- 连接 MySQL ----
    conn = get_connection()
    cursor = conn.cursor()
    ensure_table(cursor)
    conn.commit()

    # ---- 检查 MySQL 状态 ----
    mysql_total, mysql_min, mysql_max = get_mysql_table_status(cursor)
    is_first_run = (mysql_total == 0)
    print(f"\n🗄️  MySQL 状态: {mysql_total} 条 ({mysql_min} ~ {mysql_max})")

    # ---- 决策同步模式 ----
    if args.full or is_first_run:
        mode = "首次全量" if is_first_run else "强制全量 (--full)"
        print(f"\n{'=' * 60}")
        print(f"🔄 模式: {mode}")
        print(f"{'=' * 60}")

        if not is_first_run:
            if not args.dry_run:
                cursor.execute("TRUNCATE TABLE gold_prices")
                conn.commit()
                print("🗑️  已清空旧数据")
            else:
                print("[DRY-RUN] 将清空旧数据")

        if not args.dry_run:
            inserted = batch_insert(cursor, records)
            conn.commit()
            print(f"✅ 已导入 {inserted} 条")
        else:
            print(f"[DRY-RUN] 将导入 {len(records)} 条")
    else:
        # ---- 增量模式 ----
        print(f"\n{'=' * 60}")
        print(f"🔄 模式: 增量同步")
        print(f"{'=' * 60}")

        mysql_date_counts = get_mysql_date_counts(cursor)
        sync_plan = compute_sync_plan(csv_date_counts, mysql_date_counts)
        new_dates, stale_dates, skip_dates, extra_dates = sync_plan

        print(f"\n📋 差异分析:")
        print(f"   新增日期:   {len(new_dates)} 个")
        print(f"   需刷新日期: {len(stale_dates)} 个")
        print(f"   已同步日期: {len(skip_dates)} 个")
        print(f"   孤立日期:   {len(extra_dates)} 个")

        if new_dates or stale_dates or extra_dates:
            execute_sync(conn, cursor, records, csv_date_counts, mysql_date_counts,
                        sync_plan, dry_run=args.dry_run)
        else:
            print("\n✅ 数据已完整同步，无需操作。")

    # ---- 校验 ----
    print(f"\n{'=' * 60}")
    print(f"🔍 数据校验")
    print(f"{'=' * 60}")

    if not args.dry_run:
        ok = verify(conn, cursor, csv_date_counts)
    else:
        print("  [DRY-RUN] 跳过校验")
        ok = True

    # ---- 摘要 ----
    mysql_total, mysql_min, mysql_max = get_mysql_table_status(cursor)
    print(f"\n{'=' * 60}")
    print(f"📊 同步摘要")
    print(f"{'=' * 60}")
    print(f"  MySQL 记录: {mysql_total} 条")
    print(f"  日期范围:   {mysql_min} ~ {mysql_max}")
    print(f"  状态:       {'✅ 同步完成' if ok else '❌ 存在差异'}")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
