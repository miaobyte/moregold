# REAL_GDP_BILLIONS

> **分类**: 实体经济 | **数据源**: FRED | **频率**: 季
> **FRED/API**: `GDPC1` | **导入阈值**: 任意变化 ≠0
> **数据库**: 19 条记录

## 概述

美国实际GDP(十亿美元)，经济增长的最终衡量。

**可预测性**: 1.0 — 📅 日历事件 — 日期100%已知，市场提前布局

## 对金价的影响

GDP↑ → 经济好 → 风险偏好↑ → 金价↓ (负相关)

## 抓取代码

```python
df = web.DataReader('GDPC1', 'fred', start=datetime.date(2019,12,1), end=datetime.date(2026,7,1))
series = df.iloc[:, 0].dropna()
```

## 数据查询

```sql
-- 最近20条记录
SELECT event_dt, event_value, severity, cause_detail
FROM world_event
WHERE event_type = 'REAL_GDP_BILLIONS'
ORDER BY event_dt DESC LIMIT 20;

-- 按严重度统计
SELECT severity, COUNT(*) as cnt
FROM world_event
WHERE event_type = 'REAL_GDP_BILLIONS'
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
WHERE we.event_type = 'REAL_GDP_BILLIONS'
  AND we.severity >= 3
ORDER BY we.event_dt DESC LIMIT 10;
```
