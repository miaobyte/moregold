#!/usr/bin/env python3
"""
金价查询脚本
每5分钟查询一次金价并记录到本地文件
无需额外依赖，使用curl和系统命令
"""
import subprocess
import json
import os
import time
from datetime import datetime
from pathlib import Path

_RATE_CACHE = {"value": None, "ts": 0}
_RATE_TTL = 30 * 60

def get_usd_to_cny_rate():
    """
    获取美元对人民币汇率
    使用免费的汇率API
    """
    now = time.time()
    if _RATE_CACHE["value"] and now - _RATE_CACHE["ts"] < _RATE_TTL:
        return _RATE_CACHE["value"]
    try:
        # 使用 exchangerate-api 免费端点
        result = subprocess.run(
            ['curl', '-s', 'https://api.exchangerate-api.com/v4/latest/USD', 
             '-m', '10'],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            rates = data.get('rates', {})
            if 'CNY' in rates:
                _RATE_CACHE["value"] = rates['CNY']
                _RATE_CACHE["ts"] = now
                return rates['CNY']
    except Exception as e:
        print(f"⚠️ 获取汇率失败: {e}")
    
    print("⚠️ 使用备用汇率: 7.2")
    return 7.2

def get_gold_price():
    """
    使用curl获取金价
    尝试多个来源
    """
    # 方法1: 使用免费的黄金价格API
    try:
        result = subprocess.run(
            ['curl', '-s', 'https://api.gold-api.com/price/XAU', 
             '-H', 'x-access-token: demo',
             '-m', '10'],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if 'price' in data:
                return {
                    'price_usd': round(data['price'], 2),
                    'currency': 'USD',
                    'source': 'Gold-API',
                    'success': True
                }
    except Exception as e:
        pass
    
    # 方法2: 备用 - 使用网页抓取
    try:
        # 从新浪财经获取黄金价格
        result = subprocess.run(
            ['curl', '-s', 'https://hq.sinajs.cn/list=hf_GC', 
             '-H', 'Referer: https://finance.sina.com.cn/',
             '-m', '10'],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode == 0 and result.stdout.strip():
            # 解析新浪财经的返回数据
            data = result.stdout.strip()
            if 'hf_GC' in data:
                # 格式: "var hf_GC=\"1800.50,1801.00,...\""
                parts = data.split('=')
                if len(parts) > 1:
                    values = parts[1].strip('"').split(',')
                    if len(values) > 0:
                        price = float(values[0])
                        return {
                            'price_usd': round(price, 2),
                            'currency': 'USD',
                            'source': 'Sina Finance (COMEX Gold)',
                            'success': True
                        }
    except Exception as e:
        pass
    
    return {
        'success': False,
        'error': '无法获取金价'
    }

def get_aligned_time():
    """
    获取5分钟对齐的时间
    返回格式: HH:MM:00
    例如: 10:25:00, 10:20:00
    """
    now = datetime.now()
    minute = now.minute
    
    # 计算向下取整到5分钟的整数倍
    aligned_minute = (minute // 5) * 5
    
    # 创建对齐后的时间
    aligned_time = now.replace(minute=aligned_minute, second=0, microsecond=0)
    
    return aligned_time.strftime("%H:%M:%S")

def record_gold_price(price_info):
    """
    记录金价到CSV文件
    文件名格式: gold_YYYY-MM-DD.csv
    CSV格式: 时间,金价(USD/盎司),金价(CNY/克)
    """
    if not price_info.get('success'):
        return False
    
    # 获取当前日期和对齐时间
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = get_aligned_time()
    
    # 获取人民币汇率
    usd_to_cny = get_usd_to_cny_rate()
    
    # 计算人民币价格（转换为元/克）
    # 黄金价格API返回的是 USD/盎司，1盎司 = 31.1035克
    price_usd = price_info.get('price_usd', 'N/A')
    if isinstance(price_usd, (int, float)):
        # 换算公式: (USD/盎司 ÷ 31.1035克/盎司) × 人民币汇率 = CNY/克
        price_cny = round((price_usd / 31.1035) * usd_to_cny, 2)
    else:
        price_cny = 'N/A'
    
    # 准备CSV记录内容 - 逗号分隔
    csv_line = f"{time_str},{price_usd} USD/oz,{price_cny} CNY/克"
    
    # CSV文件路径（与脚本同目录）
    file_path = Path(__file__).resolve().parent / f"gold_{date_str}.csv"
    
    try:
        # 检查文件是否存在，如果不存在则写入表头
        if not file_path.exists():
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("时间,金价(USD/盎司),金价(CNY/克)\n")
        
        # 追加写入CSV记录
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(csv_line + "\n")
        
        print(f"✅ 金价已记录: {time_str} - {price_usd} USD/oz ({price_cny} CNY/克)")
        return True
    except Exception as e:
        print(f"❌ 记录失败: {e}")
        return False

def main():
    """主函数"""
    print("⏰ 开始查询金价...")
    price_info = get_gold_price()
    record_gold_price(price_info)

if __name__ == "__main__":
    main()
