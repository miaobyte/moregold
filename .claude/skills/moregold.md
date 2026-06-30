# MoreGold — 金价数据库与分析技能

## 概述

XAU/USD 金价历史数据库，部署于腾讯云 MySQL CDB，覆盖 **2020-01-01 ~ 至今（6.5 年）**。
- 2020-2025: **5 分钟粒度**（从 HistData M1 重采样）
- 2026-06-27 起: **1 分钟粒度**（实时采集）
- 价格区间: **1,452 ~ 5,417 USD/盎司**
- 2020-2025 历史数据 `price_cny = 0`，2026 年数据含实时汇率换算

## 连接信息

| 角色 | 主机 | 端口 | 用户 | 密码 | 权限 |
|------|------|------|------|------|------|
| 读写 | `bj-cdb-9ermqj8g.sql.tencentcdb.com` | 26092 | `gold` | `gold123` <!-- 密码以 GOLD_DB_URL 环境变量/密码文件为准 --> | `gold.*` 读写 |
| 只读 | `bj-cdb-9ermqj8g.sql.tencentcdb.com` | 26092 | `gold_ro` | `BNbQMsn4hhnmuw6P` <!-- 密码以 GOLD_DB_URL 环境变量/密码文件为准 --> | `gold.*` 只读 |

> 采集脚本用 `gold` 用户；分析/BI 工具用 `gold_ro`；`root` 仅 DBA 操作。

Python 连接示例：

```python
import mysql.connector
conn = mysql.connector.connect(
    host="bj-cdb-9ermqj8g.sql.tencentcdb.com",
    port=26092,
    user="gold_ro",
    password="BNbQMsn4hhnmuw6P",  # 密码以 GOLD_DB_URL 环境变量/密码文件为准
    database="gold",
    charset="utf8mb4"
)
```

## 表结构

### `gold_prices` — 主数据表

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | BIGINT PK | 自增主键 |
| `trade_date` | DATE | 交易日 |
| `trade_time` | TIME | 交易时间 |
| `price_usd` | DOUBLE | 金价 USD/盎司 |
| `price_cny` | DOUBLE | 金价 CNY/克（2020-2025 为 0） |
| `weekday` | TINYINT | 0=周一..6=周日 |
| `hour` | TINYINT | 小时 0-23 |
| `minute` | TINYINT | 分钟 |
| `dt` | DATETIME | 完整日期时间 |
| `year_week` | INT | YYYYWW 周标识 |

唯一约束: `(trade_date, trade_time)`  
索引: `(weekday, hour)`, `(year_week)`, `(dt)`

### 数据量

| 年份 | 记录数 | 价格区间 (USD) | 粒度 |
|------|--------|---------------|------|
| 2020 | 70,878 | 1,452 ~ 2,071 | 5min |
| 2021 | 70,686 | 1,677 ~ 1,957 | 5min |
| 2022 | 70,928 | 1,615 ~ 2,066 | 5min |
| 2023 | 61,794 | 1,806 ~ 2,137 | 5min |
| 2024 | 71,133 | 1,986 ~ 2,789 | 5min |
| 2025 | 70,810 | 2,616 ~ 4,546 | 5min |
| 2026 | 39,614 | 3,962 ~ 5,417 | 1min (06-27起) |

### `world_event` — 全球事件表（原 gold_event）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT PK | 自增 |
| `event_dt` | DATETIME | 事件发生时间 |
| `event_type` | VARCHAR(32) | 22 种: WAR/SURGE/PLUNGE/GAP/US10Y/CPI/SP500/... |
| `severity` | TINYINT | 1-5 级 |
| `cause_detail` | VARCHAR(512) | 事件描述/原因（可为空） |
| `source` | ENUM | AUTO / MANUAL |
| `predictability` | FLOAT | 可预测度 0-1: 0=纯突发, 1=日历预定 |
| `event_value` | DOUBLE | 事件关联数值（涨跌幅 % / 宏观因子值） |

**6,213 条**，2019-12-02 ~ 2026-06-29。价格/涨跌/方向通过 `vw_world_event` 视图 JOIN `gold_prices` 计算。

查询示例：
```sql
-- 最近战争事件
SELECT * FROM vw_world_event WHERE event_type='WAR' ORDER BY event_dt DESC;
-- 某日所有事件
SELECT * FROM vw_world_event WHERE DATE(event_dt)='2026-06-25';
```


## 常用查询

### 基础查询

```sql
-- 按周统计均价 (仅5分钟对齐数据，确保粒度一致)
SELECT year_week, AVG(price_usd) AS avg_price
FROM gold_prices WHERE weekday < 5 AND MOD(minute, 5) = 0
GROUP BY year_week ORDER BY year_week;

-- 按星期几分时段均价
SELECT weekday, hour, AVG(price_usd) AS avg_price, COUNT(*) AS n
FROM gold_prices WHERE weekday < 5 AND MOD(minute, 5) = 0
GROUP BY weekday, hour ORDER BY weekday, hour;

-- 最新金价 (全粒度)
SELECT dt, price_usd FROM gold_prices ORDER BY dt DESC LIMIT 10;
```

### 技术指标 (SQL 窗口函数实时计算)

> 以下查询均过滤 `MOD(minute, 5) = 0`，确保跨年份数据粒度一致（5min）。

```sql
-- SMA20 (20根5分钟K线 = 100分钟)
SELECT dt, price_usd,
       AVG(price_usd) OVER (ORDER BY dt ROWS 19 PRECEDING) AS sma20
FROM gold_prices WHERE MOD(minute, 5) = 0;

-- RSI14
WITH filtered AS (
    SELECT dt, price_usd
    FROM gold_prices WHERE MOD(minute, 5) = 0
),
changes AS (
    SELECT dt, price_usd,
           price_usd - LAG(price_usd, 1) OVER (ORDER BY dt) AS delta
    FROM filtered
),
gains AS (
    SELECT dt, price_usd,
           AVG(CASE WHEN delta > 0 THEN delta ELSE 0 END)
               OVER (ORDER BY dt ROWS 13 PRECEDING) AS avg_gain,
           AVG(CASE WHEN delta < 0 THEN -delta ELSE 0 END)
               OVER (ORDER BY dt ROWS 13 PRECEDING) AS avg_loss
    FROM changes
)
SELECT dt, price_usd,
       100 - 100 / (1 + avg_gain / NULLIF(avg_loss, 0)) AS rsi14
FROM gains;
```

### 策略回测核心 SQL

```sql
-- 找某周某天某小时最接近目标分钟的买入价
SELECT year_week, price_usd, dt,
       ROW_NUMBER() OVER (
           PARTITION BY year_week ORDER BY ABS(minute - 10), ABS(SECOND(dt))
       ) AS rn
FROM gold_prices
WHERE weekday = 1 AND hour = 23 AND MOD(minute, 5) = 0;

-- 日度收益率 (基于5分钟对齐数据)
SELECT trade_date, weekday,
       (SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt DESC), ',', 1) -
        SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1))
       / NULLIF(SUBSTRING_INDEX(GROUP_CONCAT(price_usd ORDER BY dt), ',', 1), 0) AS day_return
FROM gold_prices WHERE weekday < 5 AND MOD(minute, 5) = 0
GROUP BY trade_date, weekday;
```




## 注意事项

1. **CNY 价格**: 2020-2025 数据 `price_cny = 0`（历史导入未计算汇率），仅 2026 年实时数据含 CNY
2. **数据粒度**: 2020-2025 为 5min，2026-06-27 起为 1min，分析时注意粒度一致性
3. **非平稳**: 金价从 2020 年 1452 涨至 2026 年 5417，分析需使用对数收益率而非原始价格
4. **导入安全**: 使用 `INSERT IGNORE`，不会覆盖已有数据
5. **价格单位与汇报规范**: 所有计算以 **美元/盎司 (USD/oz)** 为单位；但汇报金价时必须同时给出美元/盎司和人民币/克，转换公式：
   ```
   CNY/克 = (USD/盎司 × USDCNY汇率) ÷ 31.1035，也可直接从数据库读取。
   USD/盎司 ，直接从数据库读取。
   ```

