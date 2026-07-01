# CPI_ALL_URBAN

> **分类**: 通胀 | **数据源**: FRED | **频率**: 月
> **FRED/API**: `CPIAUCSL` | **导入阈值**: 任意变化 ≠0
> **数据库**: 54 条记录

## 概述

美国消费者物价指数(全部城市消费者)，月度通胀的核心指标。

**可预测性**: 1.0 — 📅 日历事件 — 日期100%已知，市场提前布局

## 对金价的影响

CPI↑ → 通胀压力↑ → 抗通胀需求↑ → 金价↑ (正相关)

## 抓取代码

```python
df = web.DataReader('CPIAUCSL', 'fred', start=datetime.date(2019,12,1), end=datetime.date(2026,7,1))
series = df.iloc[:, 0].dropna()
```

## 数据查询

```sql
-- 最近20条记录
SELECT event_dt, event_value, severity, cause_detail
FROM world_event
WHERE event_type = 'CPI_ALL_URBAN'
ORDER BY event_dt DESC LIMIT 20;

-- 按严重度统计
SELECT severity, COUNT(*) as cnt
FROM world_event
WHERE event_type = 'CPI_ALL_URBAN'
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
WHERE we.event_type = 'CPI_ALL_URBAN'
  AND we.severity >= 3
ORDER BY we.event_dt DESC LIMIT 10;
```
