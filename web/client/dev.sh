#!/bin/bash
set -e
CLIENT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$CLIENT_DIR"

if [ ! -d "node_modules" ]; then
  echo "📦 安装依赖..."
  npm install --bin-links=false
fi

echo "🥇 GoldView React → http://localhost:5173"
echo "   (API proxy → http://localhost:8899)"
node ./node_modules/vite/bin/vite.js --port 5173
