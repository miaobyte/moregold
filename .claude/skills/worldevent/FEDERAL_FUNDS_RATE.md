# FEDERAL_FUNDS_RATE

> **分类**: 利率 | **数据源**: FRED | **频率**: 日(实时)
> **FRED/API**: `DFF` | **导入阈值**: 任意变化 ≠0
> **数据库**: 69 条记录

## 概述

美国联邦基金利率，美联储的政策利率目标。直接影响短期利率和美元走势。

**可预测性**: 1.0 — 📅 日历事件 — 日期100%已知，市场提前布局

## 对金价的影响

利率↑ → 美元资产收益↑ → 黄金持有成本↑ → 金价↓ (强负相关)

## 抓取代码

```python
import pandas_datareader.data as web
import datetime
df = web.DataReader('DFF', 'fred',
    start=datetime.date(2019,12,1),
    end=datetime.date(2026,7,1))
series = df.iloc[:, 0].dropna()
```

## 数据查询

```sql
-- 最近20条记录
SELECT event_dt, event_value, severity, cause_detail
FROM world_event
WHERE event_type = 'FEDERAL_FUNDS_RATE'
ORDER BY event_dt DESC LIMIT 20;

-- 按严重度统计
SELECT severity, COUNT(*) as cnt
FROM world_event
WHERE event_type = 'FEDERAL_FUNDS_RATE'
GROUP BY severity ORDER BY severity;
```

## 金价关联分析

```sql
-- 高严重度事件发生日的金价表现
SELECT
    we.event_dt,
    we.event_value,
    we.severity,
    we.cause_detail,
    (SELECT AVG(price_usd) FROM gold_prices
     WHERE trade_date = DATE(we.event_dt) AND MOD(minute,5)=0) as gold_avg
FROM world_event we
WHERE we.event_type = 'FEDERAL_FUNDS_RATE'
  AND we.severity >= 3
ORDER BY we.event_dt DESC LIMIT 10;
```
