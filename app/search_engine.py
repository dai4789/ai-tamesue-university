"""
ベクトル埋め込み検索エンジン

OpenAI text-embedding-3-small の埋め込みベクトルで意味検索を行う。
埋め込み未生成時はTF-IDFにフォールバック。
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).parent.parent / "data"


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


@dataclass
class ArticleResult:
    """検索結果のWeb記事（知識補強用）"""
    source: str
    title: str
    url: str
    matched_text: str
    relevance_score: float


class SearchEngine:
    """ベクトル埋め込み検索エンジン（TF-IDFフォールバック付き）"""

    def __init__(self):
        self._initialized = False
        self._videos: list[dict] = []
        self._articles: list[dict] = []
        self._video_map: dict[str, dict] = {}
        # ベクトル検索用
        self._embeddings: np.ndarray | None = None
        self._embedding_video_ids: list[str] = []
        # TF-IDFフォールバック用
        self._tfidf_vectorizer = None
        self._tfidf_matrix = None
        self._tfidf_docs: list[dict] = []
        # 記事検索用
        self._article_vectorizer = None
        self._article_matrix = None
        self._article_docs: list[dict] = []

    def load_data(self, videos: list[dict] | None = None):
        """外部からデータを渡して初期化"""
        if videos:
            self._videos = videos
        self._do_init()

    def _ensure_initialized(self):
        if self._initialized:
            return
        self._do_init()

    def _do_init(self):
        # 動画データ
        if not self._videos:
            videos_file = DATA_DIR / "videos.json"
            if videos_file.exists():
                with open(videos_file, "r", encoding="utf-8") as f:
                    self._videos = json.load(f)

        self._video_map = {v["video_id"]: v for v in self._videos}

        # 埋め込みベクトルを試行
        embeddings_file = DATA_DIR / "embeddings.npy"
        ids_file = DATA_DIR / "embedding_video_ids.json"
        if embeddings_file.exists() and ids_file.exists():
            self._embeddings = np.load(embeddings_file)
            with open(ids_file, "r", encoding="utf-8") as f:
                self._embedding_video_ids = json.load(f)
            print(f"✅ ベクトル検索モード: {self._embeddings.shape[0]} 件")
        else:
            print("⚠️ 埋め込み未生成 → TF-IDFフォールバック")
            self._build_tfidf_index()

        # Web記事
        articles_file = DATA_DIR / "web_articles.json"
        if articles_file.exists():
            with open(articles_file, "r", encoding="utf-8") as f:
                self._articles = json.load(f)
            self._build_article_index()

        self._initialized = True
        print(f"✅ 検索エンジン初期化完了: 動画 {len(self._videos)} 件, 記事 {len(self._articles)} 件")

    # ─── メイン検索 ───────────────────────────────────────

    def search(self, query: str, n_results: int = 5) -> list[VideoResult]:
        """質問に意味的に近い動画を検索"""
        self._ensure_initialized()
        if self._embeddings is not None:
            return self._search_embeddings(query, n_results)
        return self._search_tfidf(query, n_results)

    # ─── ベクトル検索 ─────────────────────────────────────

    def _search_embeddings(self, query: str, n_results: int) -> list[VideoResult]:
        query_emb = self._get_query_embedding(query)
        if query_emb is None:
            return self._search_tfidf(query, n_results)

        # コサイン類似度
        norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1  # ゼロ除算防止
        emb_norm = self._embeddings / norms
        q_norm = query_emb / np.linalg.norm(query_emb)
        similarities = emb_norm @ q_norm
        top_indices = np.argsort(similarities)[::-1]

        results = []
        seen = set()
        for idx in top_indices:
            if len(results) >= n_results:
                break
            vid = self._embedding_video_ids[idx]
            if vid in seen:
                continue
            seen.add(vid)
            video = self._video_map.get(vid)
            if not video:
                continue
            transcript = video.get("transcript", "")
            results.append(VideoResult(
                video_id=vid,
                title=video.get("title", ""),
                url=video.get("url", f"https://www.youtube.com/watch?v={vid}"),
                thumbnail=video.get("thumbnail", ""),
                upload_date=video.get("upload_date", ""),
                categories=video.get("categories", []),
                relevance_score=float(similarities[idx]),
                matched_text=transcript[:200] if transcript else video.get("title", ""),
                transcript_excerpt=transcript[:500] if transcript else "",
                duration_seconds=video.get("duration_seconds") or 0,
                view_count=video.get("view_count") or 0,
            ))
        return results

    def _get_query_embedding(self, query: str) -> np.ndarray | None:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return None
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            resp = client.embeddings.create(
                model="text-embedding-3-small", input=query, dimensions=1536,
            )
            return np.array(resp.data[0].embedding, dtype=np.float32)
        except Exception as e:
            print(f"⚠️ 埋め込み取得エラー: {e}")
            return None

    # ─── TF-IDFフォールバック ─────────────────────────────

    def _build_tfidf_index(self):
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError:
            print("⚠️ scikit-learn 未インストール → 検索不可")
            return

        self._tfidf_docs = []
        for i, v in enumerate(self._videos):
            title = v.get("title", "")
            transcript = v.get("transcript", "")
            text = f"{title} {title} {title} {transcript}"
            text = re.sub(r'[^\w\sぁ-んァ-ヶ亜-熙a-zA-Z0-9]', ' ', text)
            self._tfidf_docs.append({"video_idx": i, "text": text})

        if not self._tfidf_docs:
            return

        self._tfidf_vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(2, 4),
            max_features=50000, sublinear_tf=True,
        )
        self._tfidf_matrix = self._tfidf_vectorizer.fit_transform(
            [d["text"] for d in self._tfidf_docs]
        )

    def _search_tfidf(self, query: str, n_results: int) -> list[VideoResult]:
        if self._tfidf_vectorizer is None or self._tfidf_matrix is None:
            return []

        from sklearn.metrics.pairwise import cosine_similarity
        q = re.sub(r'[^\w\sぁ-んァ-ヶ亜-熙a-zA-Z0-9]', ' ', query)
        query_vec = self._tfidf_vectorizer.transform([q])
        scores = cosine_similarity(query_vec, self._tfidf_matrix).flatten()
        top = np.argsort(scores)[::-1][:n_results]

        results = []
        for idx in top:
            if scores[idx] <= 0:
                continue
            v = self._videos[idx]
            transcript = v.get("transcript", "")
            results.append(VideoResult(
                video_id=v.get("video_id", ""),
                title=v.get("title", ""),
                url=v.get("url", ""),
                thumbnail=v.get("thumbnail", ""),
                upload_date=v.get("upload_date", ""),
                categories=v.get("categories", []),
                relevance_score=float(scores[idx]),
                matched_text=transcript[:200] if transcript else v.get("title", ""),
                transcript_excerpt=transcript[:500] if transcript else "",
                duration_seconds=v.get("duration_seconds") or 0,
                view_count=v.get("view_count") or 0,
            ))
        return results

    # ─── 記事検索 ─────────────────────────────────────────

    def _build_article_index(self):
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError:
            return

        self._article_docs = []
        for i, a in enumerate(self._articles):
            body = a.get("body", "") or a.get("content", "")
            if not body:
                continue
            title = a.get("title", "")
            text = re.sub(r'[^\w\sぁ-んァ-ヶ亜-熙a-zA-Z0-9]', ' ', f"{title} {body}")
            self._article_docs.append({"article_idx": i, "text": text, "body": body})

        if not self._article_docs:
            return

        self._article_vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(2, 4),
            max_features=50000, sublinear_tf=True,
        )
        self._article_matrix = self._article_vectorizer.fit_transform(
            [d["text"] for d in self._article_docs]
        )

    def search_articles(self, query: str, n_results: int = 3) -> list[ArticleResult]:
        self._ensure_initialized()
        if self._article_matrix is None or not self._article_docs:
            return []

        from sklearn.metrics.pairwise import cosine_similarity
        q = re.sub(r'[^\w\sぁ-んァ-ヶ亜-熙a-zA-Z0-9]', ' ', query)
        query_vec = self._article_vectorizer.transform([q])
        scores = cosine_similarity(query_vec, self._article_matrix).flatten()
        top = np.argsort(scores)[::-1][:n_results]

        return [
            ArticleResult(
                source=self._articles[self._article_docs[idx]["article_idx"]].get("source", ""),
                title=self._articles[self._article_docs[idx]["article_idx"]].get("title", ""),
                url=self._articles[self._article_docs[idx]["article_idx"]].get("url", ""),
                matched_text=self._article_docs[idx]["body"][:400],
                relevance_score=float(scores[idx]),
            )
            for idx in top if scores[idx] > 0
        ]

    # ─── ユーティリティ ───────────────────────────────────

    @property
    def total_videos(self) -> int:
        self._ensure_initialized()
        return len(self._videos)

    @property
    def videos(self) -> list[dict]:
        self._ensure_initialized()
        return self._videos

    def get_video_details(self, video_id: str) -> dict | None:
        self._ensure_initialized()
        return self._video_map.get(video_id)
