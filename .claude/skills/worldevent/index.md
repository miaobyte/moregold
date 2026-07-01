# world_event 事件中心

`world_event` 是 gold 库的宏观因子事件表，与 `gold_prices` 并列。

## 表结构

| 列 | 说明 |
|----|------|
| `event_dt` | 事件日期 |
| `event_type` | 事件类型（见下方清单） |
| `event_value` | 变化后的新值 |
| `severity` | 1-5 严重度 (<2σ=1, 2-3σ=3, >3σ=5) |
| `cause_detail` | 变化详情 (如 `4.25→4.50`) |
| `source` | AUTO / MANUAL |
| `predictability` | 是否可预测。0.0=完全突发，0.2低概率预测，0.5概率预测, 1.0=日历事件，固定发生 |

## 事件类型清单

详见各 `{event_type}.md`：

- [FEDERAL_FUNDS_RATE](FEDERAL_FUNDS_RATE.md)
- [TREASURY_5Y_YIELD](TREASURY_5Y_YIELD.md)
- [TREASURY_10Y_YIELD](TREASURY_10Y_YIELD.md)
- [TREASURY_30Y_YIELD](TREASURY_30Y_YIELD.md)
- [TIPS_5Y_REAL_YIELD](TIPS_5Y_REAL_YIELD.md)
- [TIPS_10Y_REAL_YIELD](TIPS_10Y_REAL_YIELD.md)
- [TIPS_30Y_REAL_YIELD](TIPS_30Y_REAL_YIELD.md)
- [BREAKEVEN_10Y_INFLATION](BREAKEVEN_10Y_INFLATION.md)
- [TREASURY_10Y2Y_SPREAD](TREASURY_10Y2Y_SPREAD.md)
- [CPI_ALL_URBAN](CPI_ALL_URBAN.md)
- [CORE_CPI_EX_FOOD_ENERGY](CORE_CPI_EX_FOOD_ENERGY.md)
- [TRADE_WEIGHTED_USD_BROAD](TRADE_WEIGHTED_USD_BROAD.md)
- [USD_INDEX_ADVANCED_ECONOMIES](USD_INDEX_ADVANCED_ECONOMIES.md)
- [EUR_USD_EXCHANGE_RATE](EUR_USD_EXCHANGE_RATE.md)
- [USD_CNY_EXCHANGE_RATE](USD_CNY_EXCHANGE_RATE.md)
- [UNEMPLOYMENT_RATE](UNEMPLOYMENT_RATE.md)
- [REAL_GDP_BILLIONS](REAL_GDP_BILLIONS.md)
- [M2_MONEY_SUPPLY](M2_MONEY_SUPPLY.md)
- [FED_TOTAL_ASSETS](FED_TOTAL_ASSETS.md)
- [VIX_VOLATILITY_INDEX](VIX_VOLATILITY_INDEX.md)
- [S_AND_P_500_INDEX](S_AND_P_500_INDEX.md)
- [DOW_JONES_INDEX](DOW_JONES_INDEX.md)
- [NASDAQ_100_INDEX](NASDAQ_100_INDEX.md)
- [HIGH_YIELD_CREDIT_SPREAD](HIGH_YIELD_CREDIT_SPREAD.md)
- [WTI_CRUDE_OIL_SPOT](WTI_CRUDE_OIL_SPOT.md)
- [COPPER_PRICE_TONNE](COPPER_PRICE_TONNE.md)
- [GOLD_COT_MANAGED_MONEY_NET](GOLD_COT_MANAGED_MONEY_NET.md)
- [GOLD_ETF_PRICE_HKD](GOLD_ETF_PRICE_HKD.md)
- [GEOPOLITICAL_RISK_INDEX](GEOPOLITICAL_RISK_INDEX.md)

## 可用数据源

| 数据源 | 类型 | 状态 |
|--------|------|------|
| **FRED** | API | ✅ `pandas_datareader` |
| **东方财富** | HTTP | ✅ `urllib` + JSON |
| **CFTC COT** | HTTP | ✅ `urllib` + ZIP |
| Yahoo Finance / 新浪 / Investing / Stooq | — | ❌ 国内不可用 |

## 导入规则

- **离散因子**: 值变化≠0 写入一条
- **连续因子**: 日变化 >1σ 写入一条
- **severity**: <2σ=1, 2-3σ=3, >3σ=5
