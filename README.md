# 金价监控系统

自动采集金价并保存为每日 CSV，同时计算基础技术指标。

## 功能

- 定时采集（默认每 5 分钟）
- USD/盎司 与 CNY/克
- CSV 按日期存档
- 基础技术分析（MA、波动率、趋势）

## 使用

运行采集脚本：

python3 gold_price_fetcher.py

## 数据格式

CSV 列：时间,金价(USD/盎司),金价(CNY/克),来源

换算：$CNY/克=(USD/盎司 ÷ 31.1035) × 汇率$

## 配置

可在代码中调整：

- FETCH_INTERVAL
- VOLATILITY_THRESHOLD
- MA_PERIOD
- DEFAULT_USD_TO_CNY

## 风险提示

仅供学习与研究，不构成投资建议。数据来自第三方接口，可能延迟或不可用。
