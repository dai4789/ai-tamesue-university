"""
YouTube動画データ自動取得モジュール

アプリ起動時にYouTube Data API v3を使ってチャンネルの全動画メタデータと
トランスクリプト（字幕）を取得し、data/videos.json を更新します。
"""

import json
import os
import re
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
VIDEOS_FILE = DATA_DIR / "videos.json"

CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "UCOCFSMb1OH3plgfzz9iL2Bg")
MAX_RESULTS_PER_PAGE = 50


def fetch_and_update_videos():
    """YouTube APIから動画データを取得してvideos.jsonを更新"""
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        print("⚠️ YOUTUBE_API_KEY が未設定のため動画取得をスキップ")
        return False

    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("⚠️ google-api-python-client がないため動画取得をスキップ")
        return False

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            TranscriptsDisabled, NoTranscriptFound, VideoUnavailable,
        )
        has_transcript_api = True
    except ImportError:
        has_transcript_api = False
        print("⚠️ youtube-transcript-api がないためトランスクリプト取得をスキップ")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 既存データ読み込み
    existing_videos = {}
    if VIDEOS_FILE.exists():
        with open(VIDEOS_FILE, "r", encoding="utf-8") as f:
            existing_data = json.load(f)
            existing_videos = {v["video_id"]: v for v in existing_data}
        print(f"📂 既存データ: {len(existing_videos)} 件")

    try:
        youtube = build("youtube", "v3", developerKey=api_key)

        # 1. アップロードプレイリストID取得
        print(f"📡 チャンネル {CHANNEL_ID} の動画を取得中...")
        ch_response = youtube.channels().list(
            part="contentDetails", id=CHANNEL_ID,
        ).execute()

        if not ch_response.get("items"):
            print(f"❌ チャンネル {CHANNEL_ID} が見つかりません")
            return False

        uploads_id = ch_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # 2. 全動画IDを取得
        video_ids = []
        next_page = None
        while True:
            pl_response = youtube.playlistItems().list(
                part="contentDetails", playlistId=uploads_id,
                maxResults=MAX_RESULTS_PER_PAGE, pageToken=next_page,
            ).execute()
            for item in pl_response.get("items", []):
                video_ids.append(item["contentDetails"]["videoId"])
            next_page = pl_response.get("nextPageToken")
            if not next_page:
                break
        print(f"✅ {len(video_ids)} 件の動画を検出")

        # 3. 動画の詳細情報をバッチ取得
        videos = []
        for i in range(0, len(video_ids), MAX_RESULTS_PER_PAGE):
            batch = video_ids[i:i + MAX_RESULTS_PER_PAGE]
            v_response = youtube.videos().list(
                part="snippet,contentDetails,statistics",
                id=",".join(batch),
            ).execute()

            for item in v_response.get("items", []):
                snippet = item["snippet"]
                stats = item.get("statistics", {})
                duration_str = item.get("contentDetails", {}).get("duration", "PT0S")
                duration_seconds = _parse_duration(duration_str)

                videos.append({
                    "video_id": item["id"],
                    "title": snippet["title"],
                    "description": snippet.get("description", ""),
                    "upload_date": snippet["publishedAt"][:10],
                    "duration_seconds": duration_seconds,
                    "view_count": int(stats.get("viewCount", 0)),
                    "url": f"https://www.youtube.com/watch?v={item['id']}",
                    "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url",
                        f"https://img.youtube.com/vi/{item['id']}/hqdefault.jpg"),
                })

        # 4. トランスクリプト取得
        if has_transcript_api:
            ytt_api = YouTubeTranscriptApi()
            for i, video in enumerate(videos):
                vid = video["video_id"]
                # 既存データにトランスクリプトがあればスキップ
                if vid in existing_videos and existing_videos[vid].get("transcript"):
                    video["transcript"] = existing_videos[vid]["transcript"]
                else:
                    video["transcript"] = _fetch_transcript(ytt_api, vid)
                    if video["transcript"]:
                        print(f"  📝 [{i+1}/{len(videos)}] {video['title'][:40]}... ✅")
                    time.sleep(0.3)

                # カテゴリ分類
                video["categories"] = _categorize(
                    video["title"], video.get("description", ""), video.get("transcript"))

                if (i + 1) % 50 == 0:
                    print(f"  ... {i+1}/{len(videos)} 処理済み")
        else:
            for video in videos:
                vid = video["video_id"]
                if vid in existing_videos:
                    video["transcript"] = existing_videos[vid].get("transcript")
                    video["categories"] = existing_videos[vid].get("categories", [])
                else:
                    video["transcript"] = None
                    video["categories"] = _categorize(
                        video["title"], video.get("description", ""), None)

        # 5. 保存
        with open(VIDEOS_FILE, "w", encoding="utf-8") as f:
            json.dump(videos, f, ensure_ascii=False, indent=2)

        with_transcript = sum(1 for v in videos if v.get("transcript"))
        print(f"📊 完了: {len(videos)} 件 (トランスクリプトあり: {with_transcript} 件)")
        return True

    except Exception as e:
        print(f"❌ 動画取得エラー: {type(e).__name__}: {e}")
        return False


def _parse_duration(duration_str: str) -> int:
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return 0
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    return h * 3600 + m * 60 + s


def _fetch_transcript(ytt_api, video_id: str) -> str | None:
    from youtube_transcript_api._errors import (
        TranscriptsDisabled, NoTranscriptFound, VideoUnavailable,
    )
    try:
        transcript = ytt_api.fetch(video_id, languages=["ja", "ja-JP"])
        full_text = " ".join([entry.text for entry in transcript])
        return re.sub(r'\s+', ' ', full_text).strip()
    except (TranscriptsDisabled, NoTranscriptFound):
        try:
            transcript = ytt_api.fetch(video_id, languages=["en"])
            full_text = " ".join([entry.text for entry in transcript])
            return re.sub(r'\s+', ' ', full_text).strip()
        except Exception:
            return None
    except (VideoUnavailable, Exception):
        return None


def _categorize(title: str, description: str, transcript: str | None) -> list[str]:
    text = f"{title} {description} {transcript or ''}".lower()
    categories = []
    kw_map = {
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
    for cat, keywords in kw_map.items():
        if any(kw in text for kw in keywords):
            categories.append(cat)
    return categories or ["その他"]
