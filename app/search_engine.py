"""
セマンティック検索エンジン（TF-IDF版）

ChromaDB不要の軽量版。scikit-learnのTF-IDFで検索します。
ユーザーの質問に対して:
- 関連する動画を検索（レコメンド用）
- 関連するWeb記事を検索して知識として返す（回答の質向上用）
"""

import json
import pickle
import re
from pathlib import Path
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


DATA_DIR = Path(__file__).parent.parent / "data"
VIDEOS_FILE = DATA_DIR / "videos.json"
ARTICLES_FILE = DATA_DIR / "web_articles.json"
INDEX_FILE = DATA_DIR / "tfidf_index.pkl"


@dataclass
class ArticleResult:
    """検索結果のWeb記事（知識補強用、ユーザーには表示しない）"""
    source: str
    title: str
    url: str
    matched_text: str
    relevance_score: float


@dataclass
class VideoResult:
    """検索結果の動画"""
    video_id: str
    title: str
    url: str
    thumbnail: str
    upload_date: str
    categories: list[str]
    relevance_score: float
    matched_text: str
    transcript_excerpt: str = ""
    duration_seconds: int = 0
    view_count: int = 0


def _tokenize_ja(text: str) -> str:
    """簡易日本語トークナイザー（助詞・記号除去、n-gram風）"""
    # 記号除去
    text = re.sub(r'[^\w\sぁ-んァ-ヶ亜-熙a-zA-Z0-9]', ' ', text)
    # 連続空白を整理
    text = re.sub(r'\s+', ' ', text).strip()
    return text


class SearchEngine:
    """TF-IDFベースの検索エンジン"""

    def __init__(self):
        self._initialized = False
        self._videos: list[dict] = []
        self._articles: list[dict] = []
        self._video_docs: list[dict] = []  # {video_idx, text, type}
        self._article_docs: list[dict] = []
        self._video_vectorizer = None
        self._video_matrix = None
        self._article_vectorizer = None
        self._article_matrix = None

    def _ensure_initialized(self):
        if self._initialized:
            return

        # 動画データ読み込み
        if VIDEOS_FILE.exists():
            with open(VIDEOS_FILE, "r", encoding="utf-8") as f:
                self._videos = json.load(f)

        # Web記事データ読み込み
        if ARTICLES_FILE.exists():
            with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
                self._articles = json.load(f)

        # インデックス構築
        self._build_video_index()
        if self._articles:
            self._build_article_index()

        self._initialized = True
        print(f"✅ 検索エンジン初期化完了: 動画 {len(self._videos)} 件, 記事 {len(self._articles)} 件")

    def _build_video_index(self):
        """動画のTF-IDFインデックスを構築"""
        self._video_docs = []

        for i, video in enumerate(self._videos):
            title = video.get("title", "")
            description = video.get("description", "")
            transcript = video.get("transcript", "")
            categories = " ".join(video.get("categories", []))

            # タイトル + 説明 + カテゴリ（タイトルを強調するため3回繰り返し）
            title_doc = f"{title} {title} {title} {description} {categories}"
            self._video_docs.append({
                "video_idx": i,
                "text": _tokenize_ja(title_doc),
                "type": "title",
            })

            # トランスクリプトをチャンク分割
            if transcript:
                chunks = self._chunk_text(transcript, 400, 100)
                for chunk in chunks:
                    self._video_docs.append({
                        "video_idx": i,
                        "text": _tokenize_ja(f"{title} {chunk}"),
                        "type": "transcript",
                        "raw_text": chunk,
                    })

        if not self._video_docs:
            return

        texts = [d["text"] for d in self._video_docs]
        # n-gram (1,2) で日本語のフレーズもカバー
        self._video_vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 4),
            max_features=50000,
            sublinear_tf=True,
        )
        self._video_matrix = self._video_vectorizer.fit_transform(texts)

    def _build_article_index(self):
        """Web記事のTF-IDFインデックスを構築"""
        self._article_docs = []

        for i, article in enumerate(self._articles):
            title = article.get("title", "")
            body = article.get("body", "")
            if not body:
                continue

            # タイトル
            self._article_docs.append({
                "article_idx": i,
                "text": _tokenize_ja(f"{title} {title} {title}"),
                "type": "title",
            })

            # 本文チャンク
            chunks = self._chunk_text(body, 500, 150)
            for chunk in chunks:
                self._article_docs.append({
                    "article_idx": i,
                    "text": _tokenize_ja(f"{title} {chunk}"),
                    "type": "body",
                    "raw_text": chunk,
                })

        if not self._article_docs:
            return

        texts = [d["text"] for d in self._article_docs]
        self._article_vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 4),
            max_features=50000,
            sublinear_tf=True,
        )
        self._article_matrix = self._article_vectorizer.fit_transform(texts)

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 400, overlap: int = 100) -> list[str]:
        if not text or len(text) <= chunk_size:
            return [text] if text else []
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start += chunk_size - overlap
        return chunks

    def search(self, query: str, n_results: int = 5) -> list[VideoResult]:
        """動画を検索"""
        self._ensure_initialized()

        if self._video_matrix is None or not self._video_docs:
            return []

        query_vec = self._video_vectorizer.transform([_tokenize_ja(query)])
        scores = cosine_similarity(query_vec, self._video_matrix).flatten()

        # 動画単位で最高スコアを集約
        video_best: dict[int, dict] = {}
        for doc_idx in np.argsort(scores)[::-1]:
            score = float(scores[doc_idx])
            if score < 0.01:
                continue
            doc = self._video_docs[doc_idx]
            vidx = doc["video_idx"]
            if vidx not in video_best or score > video_best[vidx]["score"]:
                video_best[vidx] = {
                    "score": score,
                    "matched_text": doc.get("raw_text", doc["text"])[:300],
                }

        # 上位N件
        sorted_results = sorted(video_best.items(), key=lambda x: x[1]["score"], reverse=True)[:n_results]

        results = []
        for vidx, data in sorted_results:
            video = self._videos[vidx]
            categories = video.get("categories", [])
            transcript = video.get("transcript", "")

            results.append(VideoResult(
                video_id=video.get("video_id", ""),
                title=video.get("title", ""),
                url=video.get("url", ""),
                thumbnail=video.get("thumbnail", ""),
                upload_date=video.get("upload_date", ""),
                categories=categories,
                relevance_score=data["score"],
                matched_text=data["matched_text"],
                transcript_excerpt=transcript[:500] if transcript else "",
                duration_seconds=video.get("duration_seconds") or 0,
                view_count=video.get("view_count") or 0,
            ))

        return results

    def search_articles(self, query: str, n_results: int = 3) -> list[ArticleResult]:
        """Web記事を検索（知識補強用）"""
        self._ensure_initialized()

        if self._article_matrix is None or not self._article_docs:
            return []

        query_vec = self._article_vectorizer.transform([_tokenize_ja(query)])
        scores = cosine_similarity(query_vec, self._article_matrix).flatten()

        # 記事単位で集約
        article_best: dict[int, dict] = {}
        for doc_idx in np.argsort(scores)[::-1]:
            score = float(scores[doc_idx])
            if score < 0.01:
                continue
            doc = self._article_docs[doc_idx]
            aidx = doc["article_idx"]
            if aidx not in article_best or score > article_best[aidx]["score"]:
                article_best[aidx] = {
                    "score": score,
                    "matched_text": doc.get("raw_text", doc["text"])[:500],
                }

        sorted_results = sorted(article_best.items(), key=lambda x: x[1]["score"], reverse=True)[:n_results]

        return [
            ArticleResult(
                source=self._articles[aidx].get("source", ""),
                title=self._articles[aidx].get("title", ""),
                url=self._articles[aidx].get("url", ""),
                matched_text=data["matched_text"],
                relevance_score=data["score"],
            )
            for aidx, data in sorted_results
        ]

    def get_video_details(self, video_id: str) -> dict | None:
        self._ensure_initialized()
        for v in self._videos:
            if v.get("video_id") == video_id:
                return v
        return None

    @property
    def total_videos(self) -> int:
        self._ensure_initialized()
        return len(self._videos)

    @property
    def has_articles(self) -> bool:
        self._ensure_initialized()
        return len(self._articles) > 0
