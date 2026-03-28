#!/usr/bin/env python3
"""
為末大学 YouTube動画データ収集スクリプト（YouTube Data API版）

YouTube Data API v3を使ってチャンネルの全動画メタデータとトランスクリプト（字幕）を取得し、
JSONファイルとして保存します。
"""

import json
import os
import sys
import time
import re
from pathlib import Path

from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)


# ─── 設定 ─────────────────────────────────────────────
API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CHANNEL_ID = "UCOCFSMb1OH3plgfzz9iL2Bg"  # 為末大学 Tamesue Academy
OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "videos.json"
MAX_RESULTS_PER_PAGE = 50


def get_uploads_playlist_id(youtube, channel_id: str) -> str:
    """チャンネルのアップロード動画プレイリストIDを取得"""
    response = youtube.channels().list(
        part="contentDetails",
        id=channel_id,
    ).execute()

    if not response.get("items"):
        raise ValueError(f"チャンネル {channel_id} が見つかりません")

    return response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_all_video_ids(youtube, playlist_id: str) -> list[str]:
    """プレイリストから全動画IDを取得"""
    video_ids = []
    next_page_token = None

    while True:
        response = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=MAX_RESULTS_PER_PAGE,
            pageToken=next_page_token,
        ).execute()

        for item in response.get("items", []):
            video_ids.append(item["contentDetails"]["videoId"])

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

        print(f"  ... {len(video_ids)} 件取得済み")

    return video_ids


def get_video_details(youtube, video_ids: list[str]) -> list[dict]:
    """動画の詳細情報をバッチ取得（50件ずつ）"""
    all_details = []

    for i in range(0, len(video_ids), MAX_RESULTS_PER_PAGE):
        batch = video_ids[i:i + MAX_RESULTS_PER_PAGE]
        response = youtube.videos().list(
            part="snippet,contentDetails,statistics",
            id=",".join(batch),
        ).execute()

        for item in response.get("items", []):
            snippet = item["snippet"]
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})

            # ISO 8601 duration を秒に変換
            duration_str = content.get("duration", "PT0S")
            duration_seconds = parse_duration(duration_str)

            all_details.append({
                "video_id": item["id"],
                "title": snippet["title"],
                "description": snippet.get("description", ""),
                "upload_date": snippet["publishedAt"][:10],
                "duration_seconds": duration_seconds,
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "url": f"https://www.youtube.com/watch?v={item['id']}",
                "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url",
                    f"https://img.youtube.com/vi/{item['id']}/hqdefault.jpg"),
            })

        print(f"  ... 詳細 {len(all_details)}/{len(video_ids)} 件取得")

    return all_details


def parse_duration(duration_str: str) -> int:
    """ISO 8601 duration (PT1H2M3S) を秒に変換"""
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def fetch_transcript(video_id: str) -> str | None:
    """動画のトランスクリプト（字幕）を取得"""
    ytt_api = YouTubeTranscriptApi()
    try:
        transcript = ytt_api.fetch(video_id, languages=["ja", "ja-JP"])
        full_text = " ".join([entry.text for entry in transcript])
        full_text = re.sub(r'\s+', ' ', full_text).strip()
        return full_text
    except (TranscriptsDisabled, NoTranscriptFound):
        try:
            transcript = ytt_api.fetch(video_id, languages=["en"])
            full_text = " ".join([entry.text for entry in transcript])
            full_text = re.sub(r'\s+', ' ', full_text).strip()
            return full_text
        except Exception:
            return None
    except VideoUnavailable:
        return None
    except Exception as e:
        print(f"  ⚠️ トランスクリプト取得エラー ({video_id}): {type(e).__name__}")
        return None


def categorize_video(title: str, description: str, transcript: str | None) -> list[str]:
    """動画のカテゴリを推定（キーワードベース）"""
    text = f"{title} {description} {transcript or ''}".lower()
    categories = []

    category_keywords = {
        "走り方・フォーム": ["走り方", "フォーム", "姿勢", "腕振り", "接地", "ストライド", "ピッチ"],
        "トレーニング": ["トレーニング", "筋トレ", "ウエイト", "練習", "ドリル", "エクササイズ"],
        "メンタル": ["メンタル", "緊張", "集中", "モチベーション", "プレッシャー", "心理"],
        "怪我・リカバリー": ["怪我", "ケガ", "リハビリ", "ストレッチ", "回復", "痛み", "故障"],
        "ハードル": ["ハードル", "hurdle", "400m"],
        "子ども・教育": ["子ども", "子供", "キッズ", "教育", "親", "指導"],
        "対談・インタビュー": ["対談", "インタビュー", "ゲスト", "トーク"],
        "人生・キャリア": ["引退", "人生", "キャリア", "仕事", "生き方", "諦める"],
        "科学・分析": ["科学", "研究", "データ", "分析", "バイオメカニクス"],
        "速く走る": ["速く走", "スピード", "タイム", "記録", "かけっこ"],
    }

    for category, keywords in category_keywords.items():
        if any(kw in text for kw in keywords):
            categories.append(category)

    if not categories:
        categories.append("その他")

    return categories


def main():
    """メイン処理"""
    if not API_KEY:
        print("❌ YOUTUBE_API_KEY 環境変数を設定してください")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # YouTube API クライアント
    youtube = build("youtube", "v3", developerKey=API_KEY)

    # 既存データがあれば読み込み
    existing_videos = {}
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            existing_data = json.load(f)
            existing_videos = {v["video_id"]: v for v in existing_data}
        print(f"📂 既存データ: {len(existing_videos)} 件")

    # 1. アップロードプレイリストIDを取得
    print(f"📡 チャンネル {CHANNEL_ID} の動画一覧を取得中...")
    uploads_playlist_id = get_uploads_playlist_id(youtube, CHANNEL_ID)
    print(f"  プレイリストID: {uploads_playlist_id}")

    # 2. 全動画IDを取得
    video_ids = get_all_video_ids(youtube, uploads_playlist_id)
    print(f"✅ {len(video_ids)} 件の動画を検出")

    # 3. 動画の詳細情報を取得
    print(f"\n📋 動画詳細を取得中...")
    videos = get_video_details(youtube, video_ids)

    # 4. トランスクリプトを取得
    print(f"\n📝 トランスクリプトを取得中...")
    results = []
    for i, video in enumerate(videos):
        vid = video["video_id"]
        print(f"  [{i+1}/{len(videos)}] {video['title'][:50]}...")

        # 既存データにトランスクリプトがあればスキップ
        if vid in existing_videos and existing_videos[vid].get("transcript"):
            video["transcript"] = existing_videos[vid]["transcript"]
            video["categories"] = existing_videos[vid].get("categories", [])
            print(f"    ✅ キャッシュ使用")
        else:
            transcript = fetch_transcript(vid)
            video["transcript"] = transcript
            if transcript:
                print(f"    ✅ トランスクリプト取得 ({len(transcript)} 文字)")
            else:
                print(f"    ⚠️ トランスクリプトなし")
            time.sleep(0.3)

        # カテゴリ分類
        video["categories"] = categorize_video(
            video["title"],
            video.get("description", ""),
            video.get("transcript"),
        )

        results.append(video)

    # 保存
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 統計
    with_transcript = sum(1 for v in results if v.get("transcript"))
    print(f"\n{'='*50}")
    print(f"📊 完了: {len(results)} 件の動画を処理")
    print(f"   トランスクリプトあり: {with_transcript} 件")
    print(f"   トランスクリプトなし: {len(results) - with_transcript} 件")
    print(f"💾 保存先: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
