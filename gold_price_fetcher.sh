#!/usr/bin/env sh
# 金价查询脚本：每5分钟记录一次

RATE_TTL=1800
RATE_CACHE=
RATE_TS=0
LEAD_SECONDS=2

rate(){
  now=$(date +%s)
  if [ -n "$RATE_CACHE" ] && [ $((now-RATE_TS)) -lt $RATE_TTL ]; then
    echo "$RATE_CACHE"; return
  fi
  resp=$(curl -s -m 10 https://api.exchangerate-api.com/v4/latest/USD)
  cny=$(printf '%s' "$resp" | sed -n 's/.*"CNY":[ ]*\([0-9.]*\).*/\1/p')
  if [ -n "$cny" ]; then
    RATE_CACHE="$cny"; RATE_TS=$now; echo "$cny"
  fi
}

gold_price(){
  resp=$(curl -s -m 10 -H 'x-access-token: demo' https://api.gold-api.com/price/XAU)
  price=$(printf '%s' "$resp" | sed -n 's/.*"price":[ ]*\([0-9.]*\).*/\1/p')
  [ -n "$price" ] && { echo "$price"; return; }
  resp=$(curl -s -m 10 -H 'Referer: https://finance.sina.com.cn/' https://hq.sinajs.cn/list=hf_GC)
  price=$(printf '%s' "$resp" | sed -n 's/.*="\?\([0-9.]*\).*/\1/p')
  [ -n "$price" ] && echo "$price"
}

aligned_time(){
  h=$(date +%H)
  m=$(date +%M)
  am=$((10#$m/5*5))
  printf "%02d:%02d:00\n" "$h" "$am"
}

record(){
  price="$1"
  [ -z "$price" ] && return 1
  r=$(rate)
  [ -z "$r" ] && return 1
  price_cny=$(awk -v p="$price" -v r="$r" 'BEGIN{printf "%.2f", (p/31.1035)*r}')
  time_str=$(aligned_time)
  date_str=$(date +%F)
  dir=$(cd "$(dirname "$0")" && pwd)
  file="$dir/gold_${date_str}.csv"
  [ -f "$file" ] || printf "时间,金价(USD/盎司),金价(CNY/克)\n" > "$file"
  printf "%s\n" "$time_str,${price} USD/oz,${price_cny} CNY/克" >> "$file"
  echo "✅ 金价已记录: $time_str - $price USD/oz ($price_cny CNY/克)"
}

while :; do
  now_s=$(date +%s)
  min=$((10#$(date +%M)))
  next_min=$(((min/5)*5))
  next_s=$(date -j -f "%Y-%m-%d %H:%M:%S" "$(date +%F) $(date +%H):$(printf "%02d" "$next_min"):00" +%s)
  [ $now_s -ge $next_s ] && next_s=$((next_s+300))
  sleep_s=$((next_s-now_s-LEAD_SECONDS))
  [ $sleep_s -gt 0 ] && sleep $sleep_s
  while [ $(date +%s) -lt $next_s ]; do
    sleep 0.05
  done
  echo "⏰ 开始查询金价..."
  record "$(gold_price)"
done
