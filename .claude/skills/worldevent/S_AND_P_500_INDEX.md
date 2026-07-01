# S_AND_P_500_INDEX

> **分类**: 风险情绪-美股 | **数据源**: FRED | **频率**: 日
> **FRED/API**: `SP500` | **导入阈值**: 日变化 >1σ
> **数据库**: 509 条记录

## 概述

标普500指数，美国股市基准。

**可预测性**: 0.2 — 📊 市场驱动 — 连续定价，可被概率/技术/趋势预测

## 对金价的影响

股市↓ → 风险偏好↓ → 资金流向避险资产 → 金价↑ (负相关)

## 抓取代码

```python
df = web.DataReader('SP500', 'fred', start=datetime.date(2019,12,1), end=datetime.date(2026,7,1))
series = df.iloc[:, 0].dropna()
```

## 数据查询

```sql
-- 最近20条记录
SELECT event_dt, event_value, severity, cause_detail
FROM world_event
WHERE event_type = 'S_AND_P_500_INDEX'
ORDER BY event_dt DESC LIMIT 20;

-- 按严重度统计
SELECT severity, COUNT(*) as cnt
FROM world_event
WHERE event_type = 'S_AND_P_500_INDEX'
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
WHERE we.event_type = 'S_AND_P_500_INDEX'
  AND we.severity >= 3
ORDER BY we.event_dt DESC LIMIT 10;
```
