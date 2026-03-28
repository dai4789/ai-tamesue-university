# AI為末大学 - セットアップガイド

## アーキテクチャ概要

```
ユーザーの質問
    ↓
[セマンティック検索] ChromaDB + 多言語Embeddingモデル
    ↓
関連動画を上位N件取得（トランスクリプト + メタデータ）
    ↓
[Claude API] 質問 + 動画コンテキストからコメント生成
    ↓
回答（コメント + 動画推薦 + 推薦理由）
    ↓
Web UI / LINE Bot で表示
```

## クイックスタート

### 1. 環境設定

```bash
cd ai-tamesue-university
cp .env.example .env
```

`.env` を編集して以下のAPIキーを設定：

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | ✅ | Claude APIキー（回答生成に使用） |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE使用時 | LINE Developers Consoleから取得 |
| `LINE_CHANNEL_SECRET` | LINE使用時 | LINE Developers Consoleから取得 |

### 2. セットアップ & 起動（ローカル）

```bash
chmod +x run.sh
./run.sh
```

これだけで以下が自動実行されます：
1. 仮想環境の作成 & 依存パッケージのインストール
2. YouTube動画データの取得（字幕含む）
3. ベクトルインデックスの構築
4. Webサーバーの起動 → http://localhost:8000

### 3. セットアップ（Docker）

```bash
docker-compose up --build
```

## 各コンポーネントの説明

### `scripts/fetch_videos.py` - 動画データ収集

- yt-dlpでチャンネルの全動画メタデータを取得
- youtube-transcript-apiで日本語字幕（トランスクリプト）を取得
- キーワードベースのカテゴリ自動分類
- 出力: `data/videos.json`

**手動実行:**
```bash
python scripts/fetch_videos.py
```

**定期更新（cron推奨）:**
```bash
# 毎日深夜3時に更新
0 3 * * * cd /path/to/ai-tamesue-university && .venv/bin/python scripts/fetch_videos.py && .venv/bin/python scripts/build_index.py
```

### `scripts/build_index.py` - ベクトルインデックス構築

- 動画のトランスクリプトをチャンク分割（500文字、100文字オーバーラップ）
- `paraphrase-multilingual-MiniLM-L12-v2` で多言語Embedding
- ChromaDBにベクトルインデックスとして保存
- 出力: `data/chroma_db/`

### `app/search_engine.py` - セマンティック検索

- ユーザーの質問をEmbeddingに変換
- ChromaDBでコサイン類似度検索
- 動画単位で結果を集約・ランキング

### `app/ai_responder.py` - AI回答生成

- 検索結果（関連動画 + トランスクリプト）をコンテキストとしてClaude APIに送信
- 為末大の視点を反映した回答を生成
- 動画ごとに「なぜおすすめか」の理由を生成

### `app/main.py` - WebサーバーWebサーバー & LINE Bot

**API エンドポイント:**

| メソッド | パス | 説明 |
|----------|------|------|
| GET | `/` | デモWeb UI |
| POST | `/api/ask` | 質問API |
| GET | `/api/health` | ヘルスチェック |
| POST | `/webhook/line` | LINE Bot Webhook |

**質問APIの使い方:**
```bash
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "速く走るコツを教えてください", "n_videos": 3}'
```

**レスポンス例:**
```json
{
  "comment": "速く走るためには、まず「力を入れるのではなく、力を抜く」ことが大切です。為末は...",
  "recommended_videos": [
    {
      "video_id": "xxxxx",
      "title": "【永久保存版】速く走る方法",
      "url": "https://www.youtube.com/watch?v=xxxxx",
      "thumbnail": "...",
      "reason": "速く走るための基本的な身体の使い方を網羅的に解説しています",
      "relevance_score": 0.85
    }
  ],
  "query": "速く走るコツを教えてください"
}
```

## LINE Bot 設定

### 1. LINE Developers Console で設定

1. https://developers.line.biz/ にアクセス
2. 新規プロバイダー → 新規チャネル（Messaging API）を作成
3. 「Messaging API設定」から以下を取得:
   - **チャネルアクセストークン（長期）** → `LINE_CHANNEL_ACCESS_TOKEN`
   - **チャネルシークレット** → `LINE_CHANNEL_SECRET`

### 2. Webhook URL の設定

サーバーをデプロイした後、LINE Developers Console で:
- Webhook URL: `https://your-domain.com/webhook/line`
- Webhookの利用: **ON**
- 応答メッセージ: **OFF**（AIが返答するため）

### 3. デプロイ先の選択肢

| サービス | 費用 | 特徴 |
|----------|------|------|
| Railway | 無料〜$5/月 | Dockerfile対応、簡単デプロイ |
| Render | 無料〜$7/月 | 自動デプロイ、SSL付き |
| Google Cloud Run | 従量課金 | スケーラブル |
| VPS (Conoha等) | ¥600〜/月 | 自由度高い |

**Railway でのデプロイ例:**
```bash
# Railway CLIインストール
npm install -g @railway/cli

# デプロイ
railway login
railway init
railway up
```

## カスタマイズ

### 回答のトーンを変更
`app/ai_responder.py` の `SYSTEM_PROMPT` を編集してください。

### 動画のカテゴリを追加
`scripts/fetch_videos.py` の `categorize_video()` にキーワードを追加してください。

### Embeddingモデルを変更
より高精度なモデル（例: `multilingual-e5-large`）に切り替え可能です。
`app/search_engine.py` と `scripts/build_index.py` の `EMBEDDING_MODEL` を変更してください。
