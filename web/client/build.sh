#!/bin/bash
set -e
CLIENT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$CLIENT_DIR"

if [ ! -d "node_modules" ]; then
  echo "📦 安装依赖..."
  npm install --bin-links=false
fi

echo "🔨 构建..."
node ./node_modules/vite/bin/vite.js build
echo "✅ 构建完成 → ../public/"
