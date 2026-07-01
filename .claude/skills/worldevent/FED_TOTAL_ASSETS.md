# FED_TOTAL_ASSETS

> **分类**: 实体经济-央行 | **数据源**: FRED | **频率**: 周
> **FRED/API**: `WALCL` | **导入阈值**: 任意变化 ≠0
> **数据库**: 126 条记录

## 概述

美联储总资产(周度)，反映QE/QT进程。

**可预测性**: 0.5 — 📅 有固定发布日，但非交易焦点（滞后或关注度低）

## 对金价的影响

Fed扩表 → 流动性注入 → 美元贬值压力 → 金价↑ (正相关)

## 抓取代码

```python
df = web.DataReader('WALCL', 'fred', start=datetime.date(2019,12,1), end=datetime.date(2026,7,1))
series = df.iloc[:, 0].dropna()
```

## 数据查询

```sql
-- 最近20条记录
SELECT event_dt, event_value, severity, cause_detail
FROM world_event
WHERE event_type = 'FED_TOTAL_ASSETS'
ORDER BY event_dt DESC LIMIT 20;

-- 按严重度统计
SELECT severity, COUNT(*) as cnt
FROM world_event
WHERE event_type = 'FED_TOTAL_ASSETS'
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
WHERE we.event_type = 'FED_TOTAL_ASSETS'
  AND we.severity >= 3
ORDER BY we.event_dt DESC LIMIT 10;
```
