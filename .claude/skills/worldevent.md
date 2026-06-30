# world_event 数据抓取与导入经验

## 架构

```
gold 库 2 张表:
  gold_prices     — 5分钟K线 (452K行, 2020-2026)
  world_event     — 统一事件中心 (MACRO因子变化 + PRICE价格事件)

world_event 列:
  id, event_dt, event_type, event_value, severity,
  cause_detail, source, predictability, created_at
```

## 数据源总结

| 数据源 | 类型 | 可访问性 | 抓取方式 |
|--------|------|----------|----------|
| **FRED** (St. Louis Fed) | API | ✅ 国内可用 | `pandas_datareader` |
| **东方财富** (East Money) | HTTP | ✅ 国内可用 | `urllib` + JSON |
| **CFTC COT** | HTTP | ✅ 国内可用 | `urllib` + ZIP |
| **Yahoo Finance** | API/HTTP | ❌ 403屏蔽 | 不可用 |
| **新浪财经** | HTTP | ❌ 403屏蔽 | 不可用 |
| **Investing.com** | HTTP | ❌ 403屏蔽 | 不可用 |
| **Stooq** | HTTP | ❌ CF盾 | 不可用 |

---

## 事件类型抓取明细

### 利率 (6种)

| event_type | 数据源 | FRED Series | 导入阈值 | 条数 | 频率 |
|------------|--------|-------------|----------|------|------|
| `FEDERAL_FUNDS_RATE` | FRED | DFF | 任意变化 ≠0 | 69 | 实时 |
| `TREASURY_5Y_YIELD` | FRED | DGS5 | 日变化 >1σ | 462 | 日 |
| `TREASURY_10Y_YIELD` | FRED | DGS10 | 日变化 >1σ | 579 | 日 |
| `TREASURY_30Y_YIELD` | FRED | DGS30 | 日变化 >1σ | 546 | 日 |
| `TIPS_10Y_REAL_YIELD` | FRED | DFII10 | 日变化 >1σ | 483 | 日 |
| `BREAKEVEN_10Y_INFLATION` | FRED | T10YIE | 日变化 >1σ | 458 | 日 |

### 通胀 (2种)

| event_type | 数据源 | FRED Series | 导入阈值 | 条数 | 频率 |
|------------|--------|-------------|----------|------|------|
| `CPI_ALL_URBAN` | FRED | CPIAUCSL | 任意变化 ≠0 | 54 | 月 |
| `CORE_CPI_EX_FOOD_ENERGY` | FRED | CPILFESL | 任意变化 ≠0 | 54 | 月 |

### 美元 (2种)

| event_type | 数据源 | FRED Series | 导入阈值 | 条数 | 频率 |
|------------|--------|-------------|----------|------|------|
| `TRADE_WEIGHTED_USD_BROAD` | FRED | DTWEXBGS | 日变化 >1σ | 534 | 日 |
| `USD_INDEX_ADVANCED_ECONOMIES` | FRED | DTWEXAFEGS | 日变化 >1σ | 548 | 日 |

### 实体经济 (3种)

| event_type | 数据源 | FRED Series | 导入阈值 | 条数 | 频率 |
|------------|--------|-------------|----------|------|------|
| `UNEMPLOYMENT_RATE` | FRED | UNRATE | 任意变化 ≠0 | 39 | 月 |
| `REAL_GDP_BILLIONS` | FRED | GDPC1 | 任意变化 ≠0 | 19 | 季 |
| `M2_MONEY_SUPPLY` | FRED | M2SL | 任意变化 ≠0 | 55 | 月 |

### 风险情绪 (4种)

| event_type | 数据源 | FRED/EM | 导入阈值 | 条数 | 频率 |
|------------|--------|---------|----------|------|------|
| `VIX_VOLATILITY_INDEX` | FRED | VIXCLS | 日变化 >1σ | 362 | 日 |
| `S_AND_P_500_INDEX` | FRED | SP500 | 日变化 >1σ | 509 | 日 |
| `DOW_JONES_INDEX` | 东方财富 | 100.DJIA | 日变化 >1σ | 472 | 日 |
| `NASDAQ_100_INDEX` | 东方财富 | 100.NDX | 日变化 >1σ | 527 | 日 |

### 商品 (1+1种)

| event_type | 数据源 | Series/API | 导入阈值 | 条数 | 频率 |
|------------|--------|------------|----------|------|------|
| `WTI_CRUDE_OIL_SPOT` | FRED | DCOILWTICO | 日变化 >1σ | 350 | 日 |
| `COPPER_PRICE_TONNE` | FRED | PCOPPUSDM | 任意变化 ≠0 | 78 | 月 |

### 地缘 (1种)

| event_type | 数据源 | 备注 | 条数 |
|------------|--------|------|------|
| `GEOPOLITICAL_RISK_INDEX` | 手工导入 | 非 FRED 数据 | 41 |

### 黄金期货持仓 (1种, P0新增)

| event_type | 数据源 | 抓取方式 | 条数 | 频率 |
|------------|--------|----------|------|------|
| `GOLD_COT_MANAGED_MONEY_NET` | CFTC | `fut_disagg_txt_{year}.zip` | 338 | 周 |

### 价格形态 (3种, Legacy)

| event_type | 备注 | 条数 |
|------------|------|------|
| `SURGE` | 急涨 (手动标注) | 16 |
| `PLUNGE` | 急跌 (手动标注) | 26 |
| `GAP` | 跳空 (手动标注) | 10 |

---

## 抓取代码模板

### FRED (主要数据源)

```python
import pandas_datareader.data as web
import datetime

df = web.DataReader('DFF', 'fred',
    start=datetime.date(2019,12,1),
    end=datetime.date(2026,7,1))
series = df.iloc[:, 0].dropna()
```

### 东方财富 (美股指数)

```python
import urllib.request, json

url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get?' \
      'secid=100.DJIA&fields1=f1,f2,f3,f4,f5,f6' \
      '&fields2=f51,f52,f53,f54,f55,f56,f57' \
      '&klt=101&fqt=0&beg=20191201&end=20260630'

headers = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://quote.eastmoney.com/',
}
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=15) as r:
    data = json.loads(r.read())
    klines = data['data']['klines']
    # format: date,open,close,high,low,volume,...
```

### CFTC COT (黄金期货持仓)

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
                    # col[2]=date, col[7]=OI, col[13]=MM_Long, col[14]=MM_Short
```

### 不可用的数据源及原因

| 数据源 | 错误 | 原因 |
|--------|------|------|
| Yahoo Finance (`yfinance`) | Rate Limit / 403 | 国内IP被屏蔽 |
| Yahoo Finance CSV API | HTTP 403 | 同上 |
| 新浪财经 `hq.sinajs.cn` | HTTP 403 | IP限制 |
| Investing.com | HTTP 403 | IP限制 |
| Stooq.com | CF Challenge | JavaScript验证 |
| AKShare | pip依赖冲突 | 需 Python 3.9+ |
| FRED `GOLDAMGBD228NLBR` | HTTP 403 | 部分series受限 |
| FRED `PALLFNFUSDM` | HTTP 404 | Series不存在 |
| 东方财富 GLD/COMEX | null | secid不正确 |
| 东方财富白银期货 | null | secid不正确 |

---

## 导入规则

- **离散因子** (fed_funds, cpi, gdp, m2, unemployment): 值变化≠0时写入一条
- **连续因子** (us10y, vix, sp500, etc.): 日变化超过1σ时写入一条
- **severity**: <2σ=1, 2-3σ=3, >3σ=5
- **predictability**: 日历事件(FOMC/CPI)=1.0, 因子异动=0.0
- **event_value**: 存储变化后的新值

## 已知缺口

| P0 | 说明 | 状态 |
|----|------|------|
| `GOLD_ETF_HOLDINGS` | GLD ETF持仓 | ❌ 数据源不可达 |
| `SILVER_SPOT_PRICE` | 白银现货 | ❌ FRED series 不可用 |
| `COPPER_PRICE_TONNE` | 铜价 | ✅ FRED PCOPPUSDM |
| `GOLD_COT_MANAGED_MONEY_NET` | COMEX投机净多头 | ✅ CFTC COT |
