# GOLD_ETF_PRICE_HKD

> **分类**: 黄金-ETF | **数据源**: 东方财富 | **频率**: 日
> **FRED/API**: `107.GLD` | **导入阈值**: 日变化 >1σ
> **数据库**: 342 条记录

## 概述

GLD ETF港股价格(HKD)，追踪黄金现货的ETF。

**可预测性**: 0.2 — 📊 市场驱动 — 连续定价，可被概率/技术/趋势预测

## 对金价的影响

ETF价格↑ → 投资需求↑ → 金价↑ (正相关，几乎1:1联动)

## 抓取代码

```python
# 使用 scripts/download_etf.py 抓取
url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=107.GLD...'
```

## 数据查询

```sql
-- 最近20条记录
SELECT event_dt, event_value, severity, cause_detail
FROM world_event
WHERE event_type = 'GOLD_ETF_PRICE_HKD'
ORDER BY event_dt DESC LIMIT 20;

-- 按严重度统计
SELECT severity, COUNT(*) as cnt
FROM world_event
WHERE event_type = 'GOLD_ETF_PRICE_HKD'
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
WHERE we.event_type = 'GOLD_ETF_PRICE_HKD'
  AND we.severity >= 3
ORDER BY we.event_dt DESC LIMIT 10;
```
