# COPPER_PRICE_TONNE

> **分类**: 商品-工业金属 | **数据源**: FRED | **频率**: 月
> **FRED/API**: `PCOPPUSDM` | **导入阈值**: 任意变化 ≠0
> **数据库**: 78 条记录

## 概述

铜价(美元/吨)，"铜博士"反映全球工业需求。

**可预测性**: 0.2 — 📊 市场驱动 — 连续定价，可被概率/技术/趋势预测

## 对金价的影响

铜价↑ → 工业需求旺盛 → 利率预期↑ → 金价承压；但也反映通胀预期

## 抓取代码

```python
df = web.DataReader('PCOPPUSDM', 'fred', start=datetime.date(2019,12,1), end=datetime.date(2026,7,1))
series = df.iloc[:, 0].dropna()
```

## 数据查询

```sql
-- 最近20条记录
SELECT event_dt, event_value, severity, cause_detail
FROM world_event
WHERE event_type = 'COPPER_PRICE_TONNE'
ORDER BY event_dt DESC LIMIT 20;

-- 按严重度统计
SELECT severity, COUNT(*) as cnt
FROM world_event
WHERE event_type = 'COPPER_PRICE_TONNE'
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
WHERE we.event_type = 'COPPER_PRICE_TONNE'
  AND we.severity >= 3
ORDER BY we.event_dt DESC LIMIT 10;
```
