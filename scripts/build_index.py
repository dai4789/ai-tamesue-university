#!/usr/bin/env python3
"""
ベクトルインデックス構築スクリプト

videos.json と web_articles.json のデータをChromaDBにインデックスし、
セマンティック検索を可能にします。

- 動画データ → tamesue_videos コレクション（検索 + レコメンド用）
- Web記事データ → tamesue_articles コレクション（回答の知識補強用）
"""

import json
import os
import sys
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions


# ─── 設定 ─────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent / "data"
VIDEOS_FILE = DATA_DIR / "videos.json"
ARTICLES_FILE = DATA_DIR / "web_articles.json"
CHROMA_DIR = DATA_DIR / "chroma_db"

# 多言語対応のembeddingモデル（日本語もOK）
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """テキストをチャンクに分割（オーバーラップあり）"""
    if not text or len(text) <= chunk_size:
        return [text] if text else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start += chunk_size - overlap

    return chunks


def main():
    """メイン処理"""
    # 動画データ読み込み
    if not VIDEOS_FILE.exists():
        print("❌ videos.json が見つかりません。先に fetch_videos.py を実行してください。")
        sys.exit(1)

    with open(VIDEOS_FILE, "r", encoding="utf-8") as f:
        videos = json.load(f)

    print(f"📂 {len(videos)} 件の動画データを読み込み")

    # ChromaDB初期化
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Embeddingモデル
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )

    # コレクション作成（既存があれば削除して再作成）
    try:
        client.delete_collection("tamesue_videos")
    except Exception:
        pass

    collection = client.create_collection(
        name="tamesue_videos",
        embedding_function=ef,
        metadata={"description": "為末大学 YouTube動画のベクトルインデックス"},
    )

    # インデックス構築
    ids = []
    documents = []
    metadatas = []

    for video in videos:
        vid = video["video_id"]
        title = video.get("title", "")
        description = video.get("description", "")
        transcript = video.get("transcript", "")
        categories = video.get("categories", [])

        # トランスクリプトがない場合はタイトルと説明文のみ
        if transcript:
            chunks = chunk_text(transcript)
        else:
            chunks = []

        # タイトル + 説明文を最初のドキュメントとして追加
        title_doc = f"タイトル: {title}"
        if description:
            title_doc += f"\n説明: {description[:300]}"

        doc_id = f"{vid}_title"
        ids.append(doc_id)
        documents.append(title_doc)
        metadatas.append({
            "video_id": vid,
            "title": title,
            "url": video.get("url", ""),
            "thumbnail": video.get("thumbnail", ""),
            "upload_date": video.get("upload_date", ""),
            "categories": ",".join(categories),
            "chunk_type": "title",
            "duration_seconds": video.get("duration_seconds") or 0,
            "view_count": video.get("view_count") or 0,
        })

        # トランスクリプトのチャンクを追加
        for i, chunk in enumerate(chunks):
            doc_id = f"{vid}_chunk_{i}"
            ids.append(doc_id)
            documents.append(f"[{title}] {chunk}")
            metadatas.append({
                "video_id": vid,
                "title": title,
                "url": video.get("url", ""),
                "thumbnail": video.get("thumbnail", ""),
                "upload_date": video.get("upload_date", ""),
                "categories": ",".join(categories),
                "chunk_type": "transcript",
                "chunk_index": i,
                "duration_seconds": video.get("duration_seconds") or 0,
                "view_count": video.get("view_count") or 0,
            })

    # バッチでインデックスに追加
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        end = min(i + batch_size, len(ids))
        collection.add(
            ids=ids[i:end],
            documents=documents[i:end],
            metadatas=metadatas[i:end],
        )
        print(f"  📥 動画インデックス追加: {end}/{len(ids)}")

    print(f"✅ 動画インデックス: {len(ids)} ドキュメント / {len(videos)} 動画")

    # ─── Web記事のインデックス構築 ──────────────────────
    if ARTICLES_FILE.exists():
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            articles = json.load(f)

        print(f"\n📂 {len(articles)} 件のWeb記事データを読み込み")

        # 記事用コレクション
        try:
            client.delete_collection("tamesue_articles")
        except Exception:
            pass

        articles_collection = client.create_collection(
            name="tamesue_articles",
            embedding_function=ef,
            metadata={"description": "為末大のWeb記事（知識補強用）"},
        )

        art_ids = []
        art_documents = []
        art_metadatas = []

        for article in articles:
            url = article.get("url", "")
            title = article.get("title", "")
            body = article.get("body", "")
            source = article.get("source", "unknown")

            if not body:
                continue

            # タイトルドキュメント
            art_id = f"{source}_{article.get('article_id', url)}_title"
            # IDに使えない文字を除去
            art_id = art_id.replace("/", "_").replace(":", "_")[:200]
            art_ids.append(art_id)
            art_documents.append(f"[{source}] {title}")
            art_metadatas.append({
                "source": source,
                "title": title,
                "url": url,
                "published_at": article.get("published_at", ""),
                "chunk_type": "title",
                "content_type": "web_article",
            })

            # 本文チャンク
            chunks = chunk_text(body, chunk_size=600, overlap=150)
            for i, chunk in enumerate(chunks):
                art_id = f"{source}_{article.get('article_id', url)}_chunk_{i}"
                art_id = art_id.replace("/", "_").replace(":", "_")[:200]
                art_ids.append(art_id)
                art_documents.append(f"[{title}] {chunk}")
                art_metadatas.append({
                    "source": source,
                    "title": title,
                    "url": url,
                    "published_at": article.get("published_at", ""),
                    "chunk_type": "article_body",
                    "chunk_index": i,
                    "content_type": "web_article",
                })

        # バッチ追加
        for i in range(0, len(art_ids), batch_size):
            end = min(i + batch_size, len(art_ids))
            articles_collection.add(
                ids=art_ids[i:end],
                documents=art_documents[i:end],
                metadatas=art_metadatas[i:end],
            )
            print(f"  📥 記事インデックス追加: {end}/{len(art_ids)}")

        print(f"✅ 記事インデックス: {len(art_ids)} ドキュメント / {len(articles)} 記事")
    else:
        print("\n📝 web_articles.json がないため記事インデックスはスキップ")

    print(f"\n{'='*50}")
    print(f"✅ 全インデックス構築完了")
    print(f"💾 保存先: {CHROMA_DIR}")


if __name__ == "__main__":
    main()
