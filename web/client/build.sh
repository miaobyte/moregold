#!/bin/bash
set -e
CLIENT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPS_DIR="$HOME/goldview-deps"
if [ ! -d "$DEPS_DIR/node_modules" ]; then
  echo "📦 安装依赖..."
  mkdir -p "$DEPS_DIR"
  cp "$CLIENT_DIR/package.json" "$DEPS_DIR/"
  cd "$DEPS_DIR" && npm install --legacy-peer-deps
fi
export PATH="$DEPS_DIR/node_modules/.bin:$PATH"
cd "$CLIENT_DIR"
echo "🔨 构建..."
npx vite build
echo "✅ 构建完成 → ../public/"
