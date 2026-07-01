#!/bin/bash
set -e
CLIENT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPS_DIR="$HOME/goldview-deps"

# 首次运行: 安装依赖到本地目录
if [ ! -d "$DEPS_DIR/node_modules" ]; then
  echo "📦 安装依赖..."
  mkdir -p "$DEPS_DIR"
  cp "$CLIENT_DIR/package.json" "$DEPS_DIR/"
  cd "$DEPS_DIR" && npm install --legacy-peer-deps
fi

export PATH="$DEPS_DIR/node_modules/.bin:$PATH"
cd "$CLIENT_DIR"

echo "🥇 GoldView React → http://localhost:5173"
echo "   (API proxy → http://localhost:8899)"
npx vite --port 5173
