# NASDAQ_100_INDEX

> **分类**: 风险情绪-美股 | **数据源**: 东方财富 | **频率**: 日
> **FRED/API**: `100.NDX` | **导入阈值**: 日变化 >1σ
> **数据库**: 527 条记录

## 概述

纳斯达克100指数，科技股基准，从东方财富抓取。

**可预测性**: 0.2 — 📊 市场驱动 — 连续定价，可被概率/技术/趋势预测

## 对金价的影响

纳指↓ → 风险偏好↓ → 金价↑；纳指↑ → 资金追逐成长股 → 金价承压

## 抓取代码

```python
# 同 DOW_JONES_INDEX，secid=100.NDX
url = '...secid=100.NDX...'
```

## 数据查询

```sql
-- 最近20条记录
SELECT event_dt, event_value, severity, cause_detail
FROM world_event
WHERE event_type = 'NASDAQ_100_INDEX'
ORDER BY event_dt DESC LIMIT 20;

-- 按严重度统计
SELECT severity, COUNT(*) as cnt
FROM world_event
WHERE event_type = 'NASDAQ_100_INDEX'
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
WHERE we.event_type = 'NASDAQ_100_INDEX'
  AND we.severity >= 3
ORDER BY we.event_dt DESC LIMIT 10;
```
