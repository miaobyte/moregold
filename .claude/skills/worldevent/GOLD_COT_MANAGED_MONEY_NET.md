# GOLD_COT_MANAGED_MONEY_NET

> **分类**: 黄金-期货持仓 | **数据源**: CFTC COT | **频率**: 周
> **FRED/API**: `fut_disagg_txt_{year}.zip` | **导入阈值**: 周变化 >1σ
> **数据库**: 306 条记录

## 概述

COMEX黄金期货管理基金净多头持仓，反映投机资金的做多/做空倾向。

**可预测性**: 0.5 — 📅 有固定发布日，但非交易焦点（滞后或关注度低）

## 对金价的影响

净多头↑ → 投机资金看多 → 金价↑ (正相关，但极端仓位可能反向)

## 抓取代码

```python
import urllib.request, zipfile, io
for year in range(2020, 2027):
    url = f'https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        zf = zipfile.ZipFile(io.BytesIO(r.read()))
        for name in zf.namelist():
            body = zf.read(name).decode('utf-8', errors='replace')
            for line in body.split('\n'):
                if 'GOLD - COMMODITY EXCHANGE INC.' in line:
                    parts = line.replace('"','').split(',')
```

## 数据查询

```sql
-- 最近20条记录
SELECT event_dt, event_value, severity, cause_detail
FROM world_event
WHERE event_type = 'GOLD_COT_MANAGED_MONEY_NET'
ORDER BY event_dt DESC LIMIT 20;

-- 按严重度统计
SELECT severity, COUNT(*) as cnt
FROM world_event
WHERE event_type = 'GOLD_COT_MANAGED_MONEY_NET'
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
WHERE we.event_type = 'GOLD_COT_MANAGED_MONEY_NET'
  AND we.severity >= 3
ORDER BY we.event_dt DESC LIMIT 10;
```
