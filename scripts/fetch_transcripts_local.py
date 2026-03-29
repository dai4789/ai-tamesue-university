#!/usr/bin/env python3
"""
ローカルPC用：YouTube字幕一括取得スクリプト

クラウド環境（Railway等）ではYouTubeがIPをブロックするため、
このスクリプトを自宅/オフィスのPCで実行して字幕データを取得します。

使い方:
  1. pip install youtube-transcript-api
  2. python scripts/fetch_transcripts_local.py
  3. git add data/videos.json && git commit -m "Update transcripts" && git push

※ YOUTUBE_API_KEYは不要（既存のvideos.jsonから動画IDを取得）
"""

import json
import re
import sys
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
VIDEOS_FILE = DATA_DIR / "videos.json"


def fetch_transcript(ytt_api, video_id, transcript_list=None):
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
    except (VideoUnavailable, Exception) as e:
        print(f"  ⚠️ {video_id}: {type(e).__name__}")
        return None


def main():
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("❌ youtube-transcript-api がインストールされていません")
        print("   pip install youtube-transcript-api")
        sys.exit(1)

    if not VIDEOS_FILE.exists():
        print(f"❌ {VIDEOS_FILE} が見つかりません")
        print("   先にサーバーを起動してvideos.jsonを生成してください")
        sys.exit(1)

    with open(VIDEOS_FILE, "r", encoding="utf-8") as f:
        videos = json.load(f)

    total = len(videos)
    already_have = sum(1 for v in videos if v.get("transcript"))
    need_fetch = sum(1 for v in videos if not v.get("transcript"))

    print(f"📊 動画数: {total}")
    print(f"   字幕あり: {already_have}")
    print(f"   取得対象: {need_fetch}")
    print()

    if need_fetch == 0:
        print("✅ すべての動画に字幕があります！")
        return

    ytt_api = YouTubeTranscriptApi()
    fetched = 0
    failed = 0

    for i, video in enumerate(videos):
        if video.get("transcript"):
            continue

        vid = video["video_id"]
        transcript = fetch_transcript(ytt_api, vid)

        if transcript:
            video["transcript"] = transcript
            fetched += 1
            print(f"  ✅ [{fetched}/{need_fetch}] {video['title'][:50]}")
        else:
            failed += 1

        # 50件ごとに中間保存
        if (fetched + failed) % 50 == 0:
            with open(VIDEOS_FILE, "w", encoding="utf-8") as f:
                json.dump(videos, f, ensure_ascii=False, indent=2)
            print(f"  💾 中間保存 ({fetched} 取得 / {failed} 失敗)")

        # レート制限回避
        time.sleep(0.3)

    # 最終保存
    with open(VIDEOS_FILE, "w", encoding="utf-8") as f:
        json.dump(videos, f, ensure_ascii=False, indent=2)

    final_count = sum(1 for v in videos if v.get("transcript"))
    print()
    print(f"📊 完了！")
    print(f"   字幕あり: {already_have} → {final_count}")
    print(f"   新規取得: {fetched}")
    print(f"   取得失敗: {failed}")
    print()
    print("次のステップ:")
    print("  git add data/videos.json")
    print('  git commit -m "Update video transcripts"')
    print("  git push")


if __name__ == "__main__":
    main()
