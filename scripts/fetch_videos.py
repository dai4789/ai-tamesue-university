#!/usr/bin/env python3
"""
為末大学 YouTube動画データ収集スクリプト

YouTubeチャンネルから動画のメタデータとトランスクリプト（字幕）を取得し、
JSONファイルとして保存します。
"""

import json
import os
import sys
import time
import subprocess
import re
from pathlib import Path
from datetime import datetime

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)


# ─── 設定 ─────────────────────────────────────────────
CHANNEL_URL = "https://www.youtube.com/@tamesuedai"
OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "videos.json"
MAX_VIDEOS = 2000  # 全動画を取得


def get_video_list_via_ytdlp(channel_url: str, max_videos: int = MAX_VIDEOS) -> list[dict]:
    """yt-dlpを使ってチャンネルの動画一覧を取得"""
    print(f"📡 チャンネルから動画一覧を取得中... (最大 {max_videos} 件)")

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--print", "%(id)s\t%(title)s\t%(upload_date)s\t%(duration)s\t%(view_count)s\t%(description)s",
        "--playlist-end", str(max_videos),
        "--no-warnings",
        f"{channel_url}/videos",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    videos = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 5)
        if len(parts) >= 2:
            video_id = parts[0].strip()
            title = parts[1].strip() if len(parts) > 1 else ""
            upload_date = parts[2].strip() if len(parts) > 2 else ""
            duration = parts[3].strip() if len(parts) > 3 else ""
            view_count = parts[4].strip() if len(parts) > 4 else ""
            description = parts[5].strip() if len(parts) > 5 else ""

            # upload_dateを読みやすい形式に
            if upload_date and len(upload_date) == 8:
                try:
                    upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
                except Exception:
                    pass

            videos.append({
                "video_id": video_id,
                "title": title,
                "upload_date": upload_date,
                "duration_seconds": int(duration) if duration and duration.isdigit() else None,
                "view_count": int(view_count) if view_count and view_count.isdigit() else None,
                "description": description if description != "NA" else "",
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
            })

    print(f"✅ {len(videos)} 件の動画を検出")
    return videos


def fetch_transcript(video_id: str):
    """動画のトランスクリプト（字幕）を取得"""
    ytt_api = YouTubeTranscriptApi()
    try:
        # 日本語字幕を優先、なければ自動生成字幕
        transcript = ytt_api.fetch(video_id, languages=["ja", "ja-JP"])
        # テキストを結合
        full_text = " ".join([entry.text for entry in transcript])
        # 余分な空白を整理
        full_text = re.sub(r'\s+', ' ', full_text).strip()
        return full_text
    except (TranscriptsDisabled, NoTranscriptFound):
        try:
            # 英語字幕を試行
            transcript = ytt_api.fetch(video_id, languages=["en"])
            full_text = " ".join([entry.text for entry in transcript])
            full_text = re.sub(r'\s+', ' ', full_text).strip()
            return full_text
        except Exception:
            return None
    except VideoUnavailable:
        return None
    except Exception as e:
        print(f"  ⚠️ トランスクリプト取得エラー ({video_id}): {e}")
        return None


def categorize_video(title: str, description: str, transcript) -> list[str]:
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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 既存データがあれば読み込み
    existing_videos = {}
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            existing_data = json.load(f)
            existing_videos = {v["video_id"]: v for v in existing_data}
        print(f"📂 既存データ: {len(existing_videos)} 件")

    # 動画一覧を取得
    videos = get_video_list_via_ytdlp(CHANNEL_URL)

    if not videos:
        print("❌ 動画が見つかりませんでした。チャンネルURLを確認してください。")
        sys.exit(1)

    # トランスクリプトを取得
    results = []
    for i, video in enumerate(videos):
        vid = video["video_id"]
        print(f"📝 [{i+1}/{len(videos)}] {video['title'][:50]}...")

        # 既存データにトランスクリプトがあればスキップ
        if vid in existing_videos and existing_videos[vid].get("transcript"):
            video["transcript"] = existing_videos[vid]["transcript"]
            video["categories"] = existing_videos[vid].get("categories", [])
            print(f"  ✅ キャッシュ使用")
        else:
            transcript = fetch_transcript(vid)
            video["transcript"] = transcript
            if transcript:
                print(f"  ✅ トランスクリプト取得 ({len(transcript)} 文字)")
            else:
                print(f"  ⚠️ トランスクリプトなし")
            # レート制限回避
            time.sleep(0.5)

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
