# TREASURY_30Y_YIELD

> **分类**: 利率 | **数据源**: FRED | **频率**: 日
> **FRED/API**: `DGS30` | **导入阈值**: 日变化 >1σ
> **数据库**: 546 条记录

## 概述

30年期美国国债收益率，长期利率预期。

**可预测性**: 0.2 — 📊 市场驱动 — 连续定价，可被概率/技术/趋势预测

## 对金价的影响

长期利率↑ → 远期折现率↑ → 金价↓ (负相关)

## 抓取代码

```python
df = web.DataReader('DGS30', 'fred', start=datetime.date(2019,12,1), end=datetime.date(2026,7,1))
series = df.iloc[:, 0].dropna()
```

## 数据查询

```sql
-- 最近20条记录
SELECT event_dt, event_value, severity, cause_detail
FROM world_event
WHERE event_type = 'TREASURY_30Y_YIELD'
ORDER BY event_dt DESC LIMIT 20;

-- 按严重度统计
SELECT severity, COUNT(*) as cnt
FROM world_event
WHERE event_type = 'TREASURY_30Y_YIELD'
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
WHERE we.event_type = 'TREASURY_30Y_YIELD'
  AND we.severity >= 3
ORDER BY we.event_dt DESC LIMIT 10;
```
