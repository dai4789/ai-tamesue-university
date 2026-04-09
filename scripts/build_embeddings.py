#!/usr/bin/env python3
"""
ベクトル埋め込み生成スクリプト

videos.jsonの字幕テキストからOpenAI text-embedding-3-smallで
ベクトル埋め込みを生成し、NumPyファイルとして保存する。
"""

import json
import os
import sys
import time
import numpy as np
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("openai パッケージが必要です: pip install openai")
    sys.exit(1)


DATA_DIR = Path(__file__).parent.parent / "data"
VIDEOS_FILE = DATA_DIR / "videos.json"
EMBEDDINGS_FILE = DATA_DIR / "embeddings.npy"
VIDEO_IDS_FILE = DATA_DIR / "embedding_video_ids.json"

MODEL = "text-embedding-3-small"
DIMENSIONS = 1536
BATCH_SIZE = 100
MAX_TOKENS_PER_TEXT = 8000  # ~4000 chars for Japanese


def chunk_text(text: str, max_chars: int = MAX_TOKENS_PER_TEXT) -> str:
    """テキストを最大長に切り詰める"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def build_search_text(video: dict) -> str:
    """検索用テキストを構築（タイトル + カテゴリ + 字幕）"""
    parts = []
    parts.append(video.get("title", ""))
    categories = video.get("categories", [])
    if categories:
        parts.append(" ".join(categories))
    transcript = video.get("transcript", "")
    if transcript:
        parts.append(transcript)
    else:
        # 字幕がない場合はタイトルのみ（短いが検索には使える）
        description = video.get("description", "")
        if description:
            parts.append(description)
    return chunk_text(" ".join(parts))


def main():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("❌ OPENAI_API_KEY が設定されていません")
        print("   export OPENAI_API_KEY=sk-...")
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    # 動画データ読み込み
    with open(VIDEOS_FILE, "r", encoding="utf-8") as f:
        videos = json.load(f)

    print(f"📂 {len(videos)} 件の動画を読み込み")

    # 検索用テキスト構築
    texts = []
    video_ids = []
    for v in videos:
        search_text = build_search_text(v)
        if search_text.strip():
            texts.append(search_text)
            video_ids.append(v["video_id"])

    print(f"📝 {len(texts)} 件のテキストを埋め込み対象")

    # バッチで埋め込み生成
    all_embeddings = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"🔄 バッチ {batch_num}/{total_batches} ({len(batch)} 件)...")

        try:
            response = client.embeddings.create(
                model=MODEL,
                input=batch,
                dimensions=DIMENSIONS,
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)
        except Exception as e:
            print(f"❌ エラー: {e}")
            # エラーが起きても続行（ゼロベクトルで埋める）
            all_embeddings.extend([[0.0] * DIMENSIONS] * len(batch))

        # レート制限回避
        if i + BATCH_SIZE < len(texts):
            time.sleep(0.5)

    # NumPy配列として保存
    embeddings_array = np.array(all_embeddings, dtype=np.float32)
    np.save(EMBEDDINGS_FILE, embeddings_array)

    # Video IDマッピングも保存
    with open(VIDEO_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(video_ids, f, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"✅ 完了: {len(all_embeddings)} 件の埋め込みを生成")
    print(f"📐 配列サイズ: {embeddings_array.shape}")
    print(f"💾 保存先: {EMBEDDINGS_FILE} ({EMBEDDINGS_FILE.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"💾 ID一覧: {VIDEO_IDS_FILE}")


if __name__ == "__main__":
    main()
