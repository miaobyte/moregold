#!/bin/bash
export GOLD_DB_URL="mysql://root:Abc_014916@bj-cdb-9ermqj8g.sql.tencentcdb.com:26092/gold"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="/Users/lipeng"
cd /Users/lipeng/miaobyte-1252231640/github.com/miaobyte/moregold
exec /usr/bin/python3 /Users/lipeng/miaobyte-1252231640/github.com/miaobyte/moregold/scripts/collector/gold_price_fetcher.py
