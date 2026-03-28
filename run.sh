#!/bin/bash
# AI為末大学 - クイックスタートスクリプト

set -e

echo "🎓 AI為末大学 セットアップ"
echo "========================="

# .envファイルの確認
if [ ! -f .env ]; then
    echo "📋 .env.example → .env にコピーします"
    cp .env.example .env
    echo "⚠️  .env ファイルを編集して、APIキーを設定してください"
    echo "   特に ANTHROPIC_API_KEY は必須です"
    exit 1
fi

# 仮想環境
if [ ! -d .venv ]; then
    echo "📦 仮想環境を作成中..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# 依存パッケージ
echo "📦 依存パッケージをインストール中..."
pip install -r requirements.txt -q

# データ取得（初回のみ）
if [ ! -f data/videos.json ]; then
    echo ""
    echo "📡 Step 1: YouTube動画データを取得中..."
    python scripts/fetch_videos.py
fi

# Web記事取得（初回のみ）
if [ ! -f data/web_articles.json ]; then
    echo ""
    echo "📝 Step 2: Web記事データを取得中..."
    python scripts/fetch_web_articles.py
fi

# サーバー起動（TF-IDF版はインデックス構築不要、起動時に自動構築）
echo ""
echo "🚀 Step 3: サーバーを起動します..."
echo "   → http://localhost:8000"
echo "   → Ctrl+C で停止"
echo ""
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
