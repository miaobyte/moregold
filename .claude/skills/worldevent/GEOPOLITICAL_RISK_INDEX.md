# GEOPOLITICAL_RISK_INDEX

> **分类**: 地缘政治 | **数据源**: 手工导入 | **频率**: 月
> **FRED/API**: `matteoiacoviello.com/gpr` | **导入阈值**: 手工标注
> **数据库**: 41 条记录

## 概述

地缘政治风险指数(GPR)，基于新闻报道的文本分析。

**可预测性**: 0.0 — ❓ 不可预测 — 突发事件，无法提前预判

## 对金价的影响

地缘风险↑ → 不确定性↑ → 避险需求↑ → 金价↑ (事件驱动型正相关)

## 抓取代码

```
# 数据来源: https://www.matteoiacoviello.com/gpr.htm
# 下载 Excel → 手工导入 world_event
```

## 数据查询

```sql
-- 最近20条记录
SELECT event_dt, event_value, severity, cause_detail
FROM world_event
WHERE event_type = 'GEOPOLITICAL_RISK_INDEX'
ORDER BY event_dt DESC LIMIT 20;

-- 按严重度统计
SELECT severity, COUNT(*) as cnt
FROM world_event
WHERE event_type = 'GEOPOLITICAL_RISK_INDEX'
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
WHERE we.event_type = 'GEOPOLITICAL_RISK_INDEX'
  AND we.severity >= 3
ORDER BY we.event_dt DESC LIMIT 10;
```
