"""
ショート動画クリップ自動提案モジュール

YouTube長尺動画のタイムスタンプ付き字幕をAIが分析し、
Instagram Reels / TikTok / YouTube Shorts に最適な
30〜60秒の区間を自動で提案する。
"""

import json
import os
import re

import anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def fetch_timestamped_transcript(video_id: str) -> list[dict]:
    """YouTubeからタイムスタンプ付き字幕を取得"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id, languages=["ja", "ja-JP"])
        return [
            {"start": entry.start, "duration": entry.duration, "text": entry.text}
            for entry in transcript
        ]
    except Exception:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            ytt_api = YouTubeTranscriptApi()
            transcript = ytt_api.fetch(video_id, languages=["en"])
            return [
                {"start": entry.start, "duration": entry.duration, "text": entry.text}
                for entry in transcript
            ]
        except Exception as e:
            print(f"字幕取得エラー ({video_id}): {e}")
            return []


def format_transcript_with_times(segments: list[dict]) -> str:
    """タイムスタンプ付きテキストに整形"""
    lines = []
    for seg in segments:
        start = seg["start"]
        mins = int(start // 60)
        secs = int(start % 60)
        text = seg["text"].strip()
        if text:
            lines.append(f"[{mins:02d}:{secs:02d}] {text}")
    return "\n".join(lines)


def suggest_clips(video_id: str, video_title: str, n_clips: int = 3) -> list[dict]:
    """
    AIが字幕を分析して、ショート動画に最適な区間を提案する。

    Returns:
        list[dict]: 各クリップの提案情報
            - clip_number: クリップ番号
            - start_time: 開始時間 (MM:SS)
            - end_time: 終了時間 (MM:SS)
            - duration_seconds: 秒数
            - title: ショート動画用タイトル
            - description: 内容の要約
            - target_audience: core_runner | sports | educator
            - hook: 冒頭のフック文
    """
    # タイムスタンプ付き字幕を取得
    segments = fetch_timestamped_transcript(video_id)
    if not segments:
        return []

    transcript_text = format_transcript_with_times(segments)

    # 字幕が短すぎる動画はスキップ
    if len(transcript_text) < 200:
        return []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""あなたはYouTubeショート動画の編集ディレクターです。
以下は為末大（元400mハードル日本記録保持者）のYouTube動画「{video_title}」のタイムスタンプ付き字幕です。

この中から、Instagram Reels / TikTok / YouTube Shorts 向けに切り出すべき最も魅力的な {n_clips} 箇所を選んでください。

選定基準：
1. 30〜60秒の長さで完結する内容であること
2. 「へぇ！」と思える意外性のある話、または実践的なアドバイスがあること
3. 途中から見ても理解できる、自己完結した話であること
4. ランニングだけでなく、スポーツや子育て・教育に興味がある人にも刺さる内容が望ましい
5. 冒頭と末尾が自然に切れること（話の途中で始まったり終わったりしない）

字幕：
{transcript_text}

以下のJSON形式で {n_clips} 個のクリップを提案してください。JSONのみを返してください。

[
  {{
    "clip_number": 1,
    "start_time": "MM:SS",
    "end_time": "MM:SS",
    "duration_seconds": 45,
    "title": "ショート動画のタイトル（15文字以内、キャッチーに）",
    "description": "この区間の内容の要約（50文字以内）",
    "target_audience": "core_runner | sports | educator",
    "hook": "最初の2秒で視聴者を引きつけるフレーズ"
  }}
]"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if json_match:
            clips = json.loads(json_match.group())
            # 各クリップにvideo情報を追加
            for clip in clips:
                clip["video_id"] = video_id
                clip["video_title"] = video_title
                clip["video_url"] = f"https://www.youtube.com/watch?v={video_id}"
            return clips
    except Exception as e:
        print(f"AI分析エラー: {e}")

    return []


def suggest_clips_from_library(videos: list[dict], n_videos: int = 5, n_clips_per_video: int = 2) -> list[dict]:
    """
    動画ライブラリから人気動画を選び、クリップを一括提案する。

    Args:
        videos: 動画データのリスト (videos.json形式)
        n_videos: 分析する動画数
        n_clips_per_video: 動画あたりのクリップ数

    Returns:
        全クリップ提案のリスト
    """
    # 再生数が多い動画を優先（ただしShorts除外：60秒以下は除く）
    long_videos = [v for v in videos if v.get("duration_seconds", 0) > 120]
    sorted_videos = sorted(long_videos, key=lambda v: v.get("view_count", 0), reverse=True)

    all_clips = []
    for video in sorted_videos[:n_videos]:
        print(f"🔍 分析中: {video['title'][:50]}...")
        clips = suggest_clips(
            video_id=video["video_id"],
            video_title=video["title"],
            n_clips=n_clips_per_video,
        )
        all_clips.extend(clips)
        print(f"  → {len(clips)}個のクリップを提案")

    return all_clips
