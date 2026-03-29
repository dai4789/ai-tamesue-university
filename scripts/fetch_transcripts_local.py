#!/usr/bin/env python3
"""
ローカルPC用：YouTube字幕一括取得スクリプト

クラウド環境（Railway等）ではYouTubeがIPをブロックするため、
このスクリプトを自宅/オフィスのPCで実行して字幕データを取得します。

使い方:
  1. pip install youtube-transcript-api
  2. python scripts/fetch_transcripts_local.py
  3. git add data/videos.json && git commit -m "Update transcripts" && git push
"""

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
VIDEOS_FILE = DATA_DIR / "videos.json"

SERVER_URL = "https://ai-tamesue-university-production.up.railway.app"


def download_video_list():
    """サーバーから最新の動画リストをダウンロード"""
    url = f"{SERVER_URL}/api/export-videos"
    print(f"📥 サーバーから動画リストをダウンロード中...")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        print(f"   {len(data)} 件の動画を取得")
        return data
    except Exception as e:
        print(f"   ⚠️ ダウンロード失敗: {e}")
        return None


def fetch_transcript(ytt_api, video_id):
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
        return None


def main():
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("youtube-transcript-api がインストールされていません")
        print("   pip3 install youtube-transcript-api")
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # まずサーバーから最新の動画リストをダウンロード
    videos = download_video_list()

    if not videos:
        # フォールバック: ローカルのvideos.jsonを使用
        if VIDEOS_FILE.exists():
            with open(VIDEOS_FILE, "r", encoding="utf-8") as f:
                videos = json.load(f)
            print(f"   ローカルの videos.json を使用: {len(videos)} 件")
        else:
            print("動画データがありません。サーバーが起動していることを確認してください。")
            sys.exit(1)

    total = len(videos)
    already_have = sum(1 for v in videos if v.get("transcript"))
    need_fetch = sum(1 for v in videos if not v.get("transcript"))

    print(f"\n📊 動画数: {total}")
    print(f"   字幕あり: {already_have}")
    print(f"   取得対象: {need_fetch}")
    print()

    if need_fetch == 0:
        print("すべての動画に字幕があります！")
        # 保存して終了
        with open(VIDEOS_FILE, "w", encoding="utf-8") as f:
            json.dump(videos, f, ensure_ascii=False, indent=2)
        print(f"💾 {VIDEOS_FILE} に保存しました")
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
            print(f"  ✅ [{fetched}] {video['title'][:50]}")
        else:
            failed += 1

        # 50件ごとに中間保存
        if (fetched + failed) % 50 == 0 and (fetched + failed) > 0:
            with open(VIDEOS_FILE, "w", encoding="utf-8") as f:
                json.dump(videos, f, ensure_ascii=False, indent=2)
            pct = int((fetched + failed) / need_fetch * 100)
            print(f"  💾 中間保存 ({pct}% - {fetched} 取得 / {failed} 失敗)")

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
