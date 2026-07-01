# DOW_JONES_INDEX

> **分类**: 风险情绪-美股 | **数据源**: 东方财富 | **频率**: 日
> **FRED/API**: `100.DJIA` | **导入阈值**: 日变化 >1σ
> **数据库**: 472 条记录

## 概述

道琼斯工业指数，从东方财富抓取。

**可预测性**: 0.2 — 📊 市场驱动 — 连续定价，可被概率/技术/趋势预测

## 对金价的影响

道指↓ → 避险需求↑ → 金价↑

## 抓取代码

```python
import urllib.request, json
url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get?' \
      'secid=100.DJIA&fields1=f1,f2&fields2=f51,f52,f53' \
      '&klt=101&fqt=0&beg=20191201&end=20260630'
headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=15) as r:
    data = json.loads(r.read())
    klines = data['data']['klines']
```

## 数据查询

```sql
-- 最近20条记录
SELECT event_dt, event_value, severity, cause_detail
FROM world_event
WHERE event_type = 'DOW_JONES_INDEX'
ORDER BY event_dt DESC LIMIT 20;

-- 按严重度统计
SELECT severity, COUNT(*) as cnt
FROM world_event
WHERE event_type = 'DOW_JONES_INDEX'
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
WHERE we.event_type = 'DOW_JONES_INDEX'
  AND we.severity >= 3
ORDER BY we.event_dt DESC LIMIT 10;
```
