# HIGH_YIELD_CREDIT_SPREAD

> **分类**: 风险情绪-信用 | **数据源**: FRED | **频率**: 日
> **FRED/API**: `BAMLH0A0HYM2` | **导入阈值**: 日变化 >1σ
> **数据库**: 317 条记录

## 概述

美国高收益债券信用利差，衡量信用市场压力。

**可预测性**: 0.2 — 📊 市场驱动 — 连续定价，可被概率/技术/趋势预测

## 对金价的影响

利差↑ → 信用风险↑ → 避险情绪↑ → 金价↑

## 抓取代码

```python
df = web.DataReader('BAMLH0A0HYM2', 'fred', start=datetime.date(2019,12,1), end=datetime.date(2026,7,1))
series = df.iloc[:, 0].dropna()
```

## 数据查询

```sql
-- 最近20条记录
SELECT event_dt, event_value, severity, cause_detail
FROM world_event
WHERE event_type = 'HIGH_YIELD_CREDIT_SPREAD'
ORDER BY event_dt DESC LIMIT 20;

-- 按严重度统计
SELECT severity, COUNT(*) as cnt
FROM world_event
WHERE event_type = 'HIGH_YIELD_CREDIT_SPREAD'
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
WHERE we.event_type = 'HIGH_YIELD_CREDIT_SPREAD'
  AND we.severity >= 3
ORDER BY we.event_dt DESC LIMIT 10;
```
