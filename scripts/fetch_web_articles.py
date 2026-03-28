#!/usr/bin/env python3
"""
為末大 Web記事収集スクリプト

note、Tarzan Web、現代ビジネスなどから記事を収集し、
知識ベースとしてJSONに保存します。

※ 記事は「AIの回答の質を上げる知識」として使い、
  ユーザーに表示するレコメンドはYouTube動画のみです。
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


# ─── 設定 ─────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "web_articles.json"

# リクエストヘッダー
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en;q=0.9",
}

# レート制限（秒）
RATE_LIMIT = 2.0


# ─── Note.com ─────────────────────────────────────────

def fetch_note_articles(max_pages: int = 20) -> list[dict]:
    """note.com/daitamesue から記事一覧を取得"""
    print("📝 note.com の記事を取得中...")
    articles = []

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        for page in range(1, max_pages + 1):
            # noteのAPIを使って記事一覧を取得
            api_url = f"https://note.com/api/v2/creators/daitamesue/contents?kind=note&page={page}"
            try:
                resp = client.get(api_url)
                if resp.status_code != 200:
                    print(f"  ⚠️ ページ {page}: ステータス {resp.status_code}")
                    break

                data = resp.json()
                notes = data.get("data", {}).get("contents", [])

                if not notes:
                    break

                for note in notes:
                    # 無料記事のみ（有料記事はbodyが取れない）
                    article = {
                        "source": "note",
                        "article_id": str(note.get("id", "")),
                        "title": note.get("name", ""),
                        "url": f"https://note.com/daitamesue/n/{note.get('key', '')}",
                        "published_at": note.get("publishAt", ""),
                        "body": "",  # 後で個別に取得
                        "likes": note.get("likeCount", 0),
                        "is_paid": note.get("price", 0) > 0,
                    }
                    articles.append(article)

                print(f"  📄 ページ {page}: {len(notes)} 件")
                time.sleep(RATE_LIMIT)

            except Exception as e:
                print(f"  ⚠️ ページ {page} エラー: {e}")
                break

    # 無料記事の本文を取得
    free_articles = [a for a in articles if not a["is_paid"]]
    print(f"  📥 無料記事 {len(free_articles)} 件の本文を取得中...")

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        for i, article in enumerate(free_articles):
            try:
                resp = client.get(article["url"])
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")

                    # note の本文を抽出
                    body_el = soup.select_one("div.note-common-styles__textnote-body")
                    if body_el:
                        article["body"] = body_el.get_text(separator="\n", strip=True)
                    else:
                        # フォールバック: meta descriptionを使用
                        meta = soup.find("meta", {"name": "description"})
                        if meta:
                            article["body"] = meta.get("content", "")

                    if article["body"]:
                        print(f"  ✅ [{i+1}/{len(free_articles)}] {article['title'][:40]}... ({len(article['body'])}文字)")
                    else:
                        print(f"  ⚠️ [{i+1}/{len(free_articles)}] {article['title'][:40]}... (本文取得不可)")

                time.sleep(RATE_LIMIT)

            except Exception as e:
                print(f"  ⚠️ {article['title'][:30]}: {e}")

    print(f"✅ note: {len(articles)} 件取得 (無料: {len(free_articles)} 件)")
    return articles


# ─── Tarzan Web ───────────────────────────────────────

def fetch_tarzan_articles() -> list[dict]:
    """Tarzan Web の為末大の記事を取得"""
    print("📝 Tarzan Web の記事を取得中...")
    articles = []
    base_url = "https://tarzanweb.jp/author/dai_tamesue"

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        page = 1
        while True:
            url = f"{base_url}?page={page}" if page > 1 else base_url
            try:
                resp = client.get(url)
                if resp.status_code != 200:
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                article_links = soup.select("article a[href*='/post/']")

                if not article_links:
                    # 別のセレクタを試す
                    article_links = soup.select("a[href*='tarzanweb.jp']")
                    article_links = [a for a in article_links if '/post/' in a.get('href', '')]

                if not article_links:
                    break

                seen = set()
                for link in article_links:
                    href = link.get("href", "")
                    if not href or href in seen:
                        continue
                    seen.add(href)

                    full_url = href if href.startswith("http") else urljoin("https://tarzanweb.jp", href)
                    title = link.get_text(strip=True)

                    articles.append({
                        "source": "tarzan",
                        "article_id": urlparse(full_url).path,
                        "title": title or "",
                        "url": full_url,
                        "published_at": "",
                        "body": "",
                    })

                print(f"  📄 ページ {page}: {len(seen)} 件")
                page += 1
                time.sleep(RATE_LIMIT)

                if page > 10:
                    break

            except Exception as e:
                print(f"  ⚠️ ページ {page}: {e}")
                break

    # 本文取得
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        for i, article in enumerate(articles):
            try:
                resp = client.get(article["url"])
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    body_el = soup.select_one("div.article-body") or soup.select_one("article")
                    if body_el:
                        # スクリプトやスタイルを除去
                        for tag in body_el.select("script, style, nav, footer"):
                            tag.decompose()
                        article["body"] = body_el.get_text(separator="\n", strip=True)

                    # タイトル補完
                    if not article["title"]:
                        title_el = soup.select_one("h1")
                        if title_el:
                            article["title"] = title_el.get_text(strip=True)

                    if article["body"]:
                        print(f"  ✅ [{i+1}/{len(articles)}] {article['title'][:40]}... ({len(article['body'])}文字)")

                time.sleep(RATE_LIMIT)

            except Exception as e:
                print(f"  ⚠️ {article.get('title', '?')[:30]}: {e}")

    print(f"✅ Tarzan: {len(articles)} 件取得")
    return articles


# ─── 現代ビジネス ─────────────────────────────────────

def fetch_gendai_articles() -> list[dict]:
    """現代ビジネスの為末大の記事を取得"""
    print("📝 現代ビジネスの記事を取得中...")
    articles = []
    base_url = "https://gendai.media/list/author/daitamesue"

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        try:
            resp = client.get(base_url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                links = soup.select("a[href*='/articles/']")

                seen = set()
                for link in links:
                    href = link.get("href", "")
                    if not href or href in seen or "list" in href:
                        continue
                    seen.add(href)

                    full_url = href if href.startswith("http") else urljoin("https://gendai.media", href)
                    title = link.get_text(strip=True)

                    if title and len(title) > 5:
                        articles.append({
                            "source": "gendai",
                            "article_id": urlparse(full_url).path,
                            "title": title,
                            "url": full_url,
                            "published_at": "",
                            "body": "",
                        })

        except Exception as e:
            print(f"  ⚠️ 一覧取得エラー: {e}")

    # 本文取得
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        for i, article in enumerate(articles[:30]):  # 最大30件
            try:
                resp = client.get(article["url"])
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    body_el = soup.select_one("div.article-body") or soup.select_one("article")
                    if body_el:
                        for tag in body_el.select("script, style, nav, footer, aside"):
                            tag.decompose()
                        article["body"] = body_el.get_text(separator="\n", strip=True)

                    if article["body"]:
                        print(f"  ✅ [{i+1}/{len(articles)}] {article['title'][:40]}... ({len(article['body'])}文字)")

                time.sleep(RATE_LIMIT)

            except Exception as e:
                print(f"  ⚠️ {article.get('title', '?')[:30]}: {e}")

    print(f"✅ 現代ビジネス: {len(articles)} 件取得")
    return articles


# ─── Deportare Partners ──────────────────────────────

def fetch_deportare_articles() -> list[dict]:
    """Deportare Partners の記事・コラムを取得"""
    print("📝 Deportare Partners の記事を取得中...")
    articles = []

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        try:
            resp = client.get("https://www.deportarepartners.tokyo/")
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")

                # ブログやコラムのリンクを探す
                links = soup.select("a[href]")
                seen = set()
                for link in links:
                    href = link.get("href", "")
                    if any(kw in href for kw in ["/blog", "/column", "/news", "/post"]):
                        if href not in seen:
                            seen.add(href)
                            full_url = href if href.startswith("http") else urljoin("https://www.deportarepartners.tokyo", href)
                            title = link.get_text(strip=True)
                            articles.append({
                                "source": "deportare",
                                "article_id": urlparse(full_url).path,
                                "title": title or "",
                                "url": full_url,
                                "published_at": "",
                                "body": "",
                            })

        except Exception as e:
            print(f"  ⚠️ {e}")

    print(f"✅ Deportare: {len(articles)} 件取得")
    return articles


# ─── メイン処理 ───────────────────────────────────────

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 既存データ読み込み
    existing = {}
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            existing_data = json.load(f)
            existing = {a["url"]: a for a in existing_data}
        print(f"📂 既存データ: {len(existing)} 件")

    all_articles = []

    # 各ソースから取得
    try:
        all_articles.extend(fetch_note_articles())
    except Exception as e:
        print(f"⚠️ note取得失敗: {e}")

    try:
        all_articles.extend(fetch_tarzan_articles())
    except Exception as e:
        print(f"⚠️ Tarzan取得失敗: {e}")

    try:
        all_articles.extend(fetch_gendai_articles())
    except Exception as e:
        print(f"⚠️ 現代ビジネス取得失敗: {e}")

    try:
        all_articles.extend(fetch_deportare_articles())
    except Exception as e:
        print(f"⚠️ Deportare取得失敗: {e}")

    # 既存データとマージ（本文があるものは上書きしない）
    merged = {}
    for article in all_articles:
        url = article["url"]
        if url in existing and existing[url].get("body") and not article.get("body"):
            merged[url] = existing[url]
        else:
            merged[url] = article

    # 本文がある記事のみ保存
    results = [a for a in merged.values() if a.get("body")]

    # 保存
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 統計
    by_source = {}
    for a in results:
        src = a.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1

    print(f"\n{'='*50}")
    print(f"📊 完了: {len(results)} 件の記事を保存")
    for src, count in sorted(by_source.items()):
        print(f"   {src}: {count} 件")
    print(f"💾 保存先: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
