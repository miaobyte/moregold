#!/usr/bin/env python3
"""
MySQL 技术指标视图创建脚本

在 gold_db 中创建以下指标视图（供 BI 工具直接查询）：
  - vw_sma(n)      简单移动平均
  - vw_rsi(n)      相对强弱指数
  - vw_bollinger(n) 布林带
  - vw_atr(n)      平均真实波幅（价格版）
  - vw_adx(n)      趋势强度指数（价格版）
  - vw_indicators   综合指标视图

BI 工具可直接 SELECT * FROM gold_db.vw_indicators 获取所有指标。

用法:
    python3 scripts/sql/create_indicators.py
"""

import mysql.connector

DB_CONFIG = {
    "host": "localhost",
    "user": "gold",
    "password": "gold123",
    "database": "gold_db",
    "charset": "utf8mb4",
}


def get_connection():
    return mysql.connector.connect(**DB_CONFIG)


def drop_all_views(cursor):
    views = [
        "vw_sma", "vw_rsi", "vw_bollinger", "vw_atr", "vw_adx",
        "vw_indicators", "vw_price_lagged",
    ]
    for v in views:
        cursor.execute(f"DROP VIEW IF EXISTS {v}")


def create_lagged_view(cursor):
    """创建带滞后价格的基础视图。"""
    # 先找最大N值
    cursor.execute("""
        CREATE OR REPLACE VIEW vw_price_lagged AS
        SELECT
            trade_date,
            trade_time,
            dt,
            weekday,
            hour,
            price_usd,
            price_cny,
            LAG(price_usd, 1)  OVER w AS p1,
            LAG(price_usd, 2)  OVER w AS p2,
            LAG(price_usd, 3)  OVER w AS p3,
            LAG(price_usd, 4)  OVER w AS p4,
            LAG(price_usd, 5)  OVER w AS p5,
            LAG(price_usd, 10) OVER w AS p10,
            LAG(price_usd, 14) OVER w AS p14,
            LAG(price_usd, 20) OVER w AS p20,
            LAG(price_usd, 50) OVER w AS p50
        FROM gold_prices
        WINDOW w AS (ORDER BY dt)
    """)
    return "vw_price_lagged"


def create_sma_view(cursor):
    """SMA(n) = 最近 n 个价格的简单均值。"""
    # 用子查询计算不同窗口的 SMA
    cursor.execute("""
        CREATE OR REPLACE VIEW vw_sma AS
        SELECT
            dt,
            trade_date,
            trade_time,
            price_usd,
            ROUND(AVG(price_usd) OVER (ORDER BY dt ROWS 4 PRECEDING), 2)   AS sma5,
            ROUND(AVG(price_usd) OVER (ORDER BY dt ROWS 9 PRECEDING), 2)   AS sma10,
            ROUND(AVG(price_usd) OVER (ORDER BY dt ROWS 13 PRECEDING), 2)  AS sma14,
            ROUND(AVG(price_usd) OVER (ORDER BY dt ROWS 19 PRECEDING), 2)  AS sma20,
            ROUND(AVG(price_usd) OVER (ORDER BY dt ROWS 49 PRECEDING), 2)  AS sma50,
            CASE
                WHEN AVG(price_usd) OVER (ORDER BY dt ROWS 4 PRECEDING) >
                     AVG(price_usd) OVER (ORDER BY dt ROWS 19 PRECEDING)
                THEN 'UP'
                WHEN AVG(price_usd) OVER (ORDER BY dt ROWS 4 PRECEDING) <
                     AVG(price_usd) OVER (ORDER BY dt ROWS 19 PRECEDING)
                THEN 'DOWN'
                ELSE 'FLAT'
            END AS trend_ma5_ma20
        FROM gold_prices
    """)
    return "vw_sma"


def create_rsi_view(cursor):
    """RSI(14) = 100 - 100/(1 + avg_gain/avg_loss)。"""
    cursor.execute("""
        CREATE OR REPLACE VIEW vw_rsi AS
        WITH changes AS (
            SELECT
                dt,
                price_usd,
                price_usd - LAG(price_usd, 1) OVER (ORDER BY dt) AS delta
            FROM gold_prices
        ),
        gains AS (
            SELECT
                dt,
                price_usd,
                delta,
                CASE WHEN delta > 0 THEN delta ELSE 0 END AS gain,
                CASE WHEN delta < 0 THEN -delta ELSE 0 END AS loss
            FROM changes
        ),
        avg_gains AS (
            SELECT
                dt,
                price_usd,
                delta,
                ROUND(AVG(gain) OVER (ORDER BY dt ROWS 13 PRECEDING), 4) AS avg_gain,
                ROUND(AVG(loss) OVER (ORDER BY dt ROWS 13 PRECEDING), 4) AS avg_loss
            FROM gains
        )
        SELECT
            dt,
            price_usd,
            delta,
            avg_gain,
            avg_loss,
            ROUND(CASE
                WHEN avg_loss = 0 THEN 100.0
                ELSE 100.0 - 100.0 / (1.0 + avg_gain / NULLIF(avg_loss, 0))
            END, 2) AS rsi14
        FROM avg_gains
    """)
    return "vw_rsi"


def create_bollinger_view(cursor):
    """布林带 (20, 2): 中轨=SMA20, 上轨=SMA20+2σ, 下轨=SMA20-2σ, 带宽=(上-下)/中。"""
    cursor.execute("""
        CREATE OR REPLACE VIEW vw_bollinger AS
        SELECT
            dt,
            trade_date,
            trade_time,
            price_usd,
            ROUND(AVG(price_usd) OVER (ORDER BY dt ROWS 19 PRECEDING), 2) AS bb_mid,
            ROUND(AVG(price_usd) OVER (ORDER BY dt ROWS 19 PRECEDING)
                + 2 * STDDEV_SAMP(price_usd) OVER (ORDER BY dt ROWS 19 PRECEDING), 2) AS bb_upper,
            ROUND(AVG(price_usd) OVER (ORDER BY dt ROWS 19 PRECEDING)
                - 2 * STDDEV_SAMP(price_usd) OVER (ORDER BY dt ROWS 19 PRECEDING), 2) AS bb_lower,
            ROUND(4 * STDDEV_SAMP(price_usd) OVER (ORDER BY dt ROWS 19 PRECEDING)
                / NULLIF(AVG(price_usd) OVER (ORDER BY dt ROWS 19 PRECEDING), 0), 6) AS bb_width,
            ROUND((price_usd - AVG(price_usd) OVER (ORDER BY dt ROWS 19 PRECEDING))
                / NULLIF(STDDEV_SAMP(price_usd) OVER (ORDER BY dt ROWS 19 PRECEDING), 0), 4) AS bb_position
        FROM gold_prices
    """)
    return "vw_bollinger"


def create_atr_view(cursor):
    """ATR(n) = 最近 n 个价格变动绝对值的均值。"""
    cursor.execute("""
        CREATE OR REPLACE VIEW vw_atr AS
        WITH deltas AS (
            SELECT
                dt,
                price_usd,
                ABS(price_usd - LAG(price_usd, 1) OVER (ORDER BY dt)) AS true_range
            FROM gold_prices
        )
        SELECT
            dt,
            price_usd,
            true_range,
            ROUND(AVG(true_range) OVER (ORDER BY dt ROWS 13 PRECEDING), 4) AS atr14,
            ROUND(AVG(true_range) OVER (ORDER BY dt ROWS 49 PRECEDING), 4) AS atr50
        FROM deltas
    """)
    return "vw_atr"


def create_adx_view(cursor):
    """ADX(14) = 趋势强度（基于价格变化的方向性移动）。"""
    cursor.execute("""
        CREATE OR REPLACE VIEW vw_adx AS
        WITH deltas AS (
            SELECT
                dt,
                price_usd,
                price_usd - LAG(price_usd, 1) OVER (ORDER BY dt) AS delta
            FROM gold_prices
        ),
        directional AS (
            SELECT
                dt,
                price_usd,
                delta,
                CASE WHEN delta > 0 THEN delta ELSE 0 END AS up_move,
                CASE WHEN delta < 0 THEN -delta ELSE 0 END AS down_move,
                ABS(delta) AS tr
            FROM deltas
        ),
        smoothed AS (
            SELECT
                dt,
                price_usd,
                delta,
                AVG(up_move)  OVER (ORDER BY dt ROWS 13 PRECEDING) AS avg_up,
                AVG(down_move) OVER (ORDER BY dt ROWS 13 PRECEDING) AS avg_down,
                AVG(tr)       OVER (ORDER BY dt ROWS 13 PRECEDING) AS avg_tr
            FROM directional
        )
        SELECT
            dt,
            price_usd,
            delta,
            ROUND(100 * avg_up / NULLIF(avg_tr, 0), 2) AS plus_di,
            ROUND(100 * avg_down / NULLIF(avg_tr, 0), 2) AS minus_di,
            ROUND(100 * ABS(avg_up - avg_down) / NULLIF(avg_up + avg_down, 0), 2) AS adx14
        FROM smoothed
    """)
    return "vw_adx"


def create_combined_view(cursor):
    """综合指标视图：一行包含所有指标，方便 BI 工具直接使用。"""
    cursor.execute("""
        CREATE OR REPLACE VIEW vw_indicators AS
        SELECT
            p.trade_date,
            p.trade_time,
            p.dt,
            p.weekday,
            p.hour,
            p.price_usd,
            p.price_cny,
            s.sma5,  s.sma10,  s.sma14,  s.sma20,  s.sma50,
            s.trend_ma5_ma20,
            r.rsi14,
            bb.bb_mid,  bb.bb_upper,  bb.bb_lower,
            bb.bb_width, bb.bb_position,
            a.atr14,    a.atr50,
            adx.plus_di, adx.minus_di, adx.adx14
        FROM gold_prices p
        LEFT JOIN vw_sma       s   ON p.dt = s.dt
        LEFT JOIN vw_rsi       r   ON p.dt = r.dt
        LEFT JOIN vw_bollinger bb  ON p.dt = bb.dt
        LEFT JOIN vw_atr       a   ON p.dt = a.dt
        LEFT JOIN vw_adx       adx ON p.dt = adx.dt
    """)
    return "vw_indicators"


def main():
    print("🔧 创建 MySQL 技术指标视图...")
    conn = get_connection()
    cursor = conn.cursor()

    drop_all_views(cursor)
    print()

    for name, creator in [
        ("vw_price_lagged", create_lagged_view),
        ("vw_sma",          create_sma_view),
        ("vw_rsi",          create_rsi_view),
        ("vw_bollinger",    create_bollinger_view),
        ("vw_atr",          create_atr_view),
        ("vw_adx",          create_adx_view),
        ("vw_indicators",   create_combined_view),
    ]:
        result = creator(cursor)
        print(f"  ✅ {result}")

    conn.commit()

    # 验证
    cursor.execute("SELECT COUNT(*) FROM vw_indicators")
    n = cursor.fetchone()[0]
    print(f"\n📊 vw_indicators 共 {n} 行")

    # 展示最新一行数据
    cursor.execute("""
        SELECT trade_date, trade_time,
               ROUND(price_usd, 2) AS price,
               sma5, sma20, rsi14,
               bb_mid, bb_upper, bb_lower,
               atr14, adx14,
               trend_ma5_ma20
        FROM vw_indicators
        ORDER BY dt DESC LIMIT 3
    """)
    cols = [d[0] for d in cursor.description]
    print(f"\n📋 最新 3 条指标 ({', '.join(cols)}):")
    for row in cursor.fetchall():
        print(f"   {row}")

    print("\n✅ 指标视图创建完成。BI 工具可查询: gold_db.vw_indicators")
    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
