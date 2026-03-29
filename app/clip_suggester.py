"""
ショート動画クリップ自動提案モジュール

YouTube長尺動画の字幕をAIが分析し、
Instagram Reels / TikTok / YouTube Shorts に最適な
30〜60秒の区間を自動で提案する。

既に取得済みのトランスクリプトデータ（videos.json）を使用するため、
YouTubeへの追加リクエストは不要。
"""

import json
import os
import re

import anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def suggest_clips(video_id: str, video_title: str, transcript: str,
                  duration_seconds: int = 0, n_clips: int = 3) -> list[dict]:
    """
    AIが字幕を分析して、ショート動画に最適な区間を提案する。

    Args:
        video_id: YouTube動画ID
        video_title: 動画タイトル
        transcript: 字幕テキスト（videos.jsonに保存済みのもの）
        duration_seconds: 動画の長さ（秒）
        n_clips: 提案するクリップ数

    Returns:
        list[dict]: 各クリップの提案情報
    """
    if not transcript or len(transcript) < 200:
        return []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    duration_info = ""
    if duration_seconds > 0:
        mins = duration_seconds // 60
        secs = duration_seconds % 60
        duration_info = f"\nこの動画の長さは{mins}分{secs}秒です。"

    prompt = f"""あなたはYouTubeショート動画の編集ディレクターです。
以下は為末大（元400mハードル日本記録保持者）のYouTube動画「{video_title}」の字幕テキストです。{duration_info}

この字幕の中から、Instagram Reels / TikTok / YouTube Shorts 向けに切り出すべき最も魅力的な {n_clips} 箇所を選んでください。

選定基準：
1. 30〜60秒の長さで完結する内容であること（日本語の話し言葉は1秒あたり約4〜5文字）
2. 「へぇ！」と思える意外性のある話、または実践的なアドバイスがあること
3. 途中から見ても理解できる、自己完結した話であること
4. ランニングだけでなく、スポーツや子育て・教育に興味がある人にも刺さる内容が望ましい
5. 冒頭と末尾が自然に切れること（話の途中で始まったり終わったりしない）

字幕テキスト：
{transcript[:8000]}

以下のJSON形式で {n_clips} 個のクリップを提案してください。JSONのみを返してください。
transcript_excerptには、切り出すべき部分の字幕テキストの冒頭30文字程度を含めてください（動画内で該当箇所を見つけるための目印になります）。

[
  {{
    "clip_number": 1,
    "estimated_position": "序盤 | 中盤 | 終盤",
    "transcript_excerpt": "切り出し部分の字幕冒頭30文字...",
    "duration_seconds": 45,
    "title": "ショート動画のタイトル（15文字以内、キャッチーに）",
    "description": "この区間の内容の要約（50文字以内）",
    "target_audience": "core_runner | sports | educator",
    "hook": "最初の2秒で視聴者を引きつけるフレーズ",
    "caption_text": "投稿時のキャプション案（ハッシュタグ含む、100文字以内）"
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
            for clip in clips:
                clip["video_id"] = video_id
                clip["video_title"] = video_title
                clip["video_url"] = f"https://www.youtube.com/watch?v={video_id}"
            return clips
    except Exception as e:
        print(f"AI分析エラー: {e}")

    return []


def suggest_clips_from_library(videos: list[dict], n_videos: int = 5,
                               n_clips_per_video: int = 2) -> list[dict]:
    """
    動画ライブラリから人気動画を選び、クリップを一括提案する。

    Args:
        videos: 動画データのリスト (videos.json形式)
        n_videos: 分析する動画数
        n_clips_per_video: 動画あたりのクリップ数

    Returns:
        全クリップ提案のリスト
    """
    # 再生数が多い長尺動画を優先（Shorts除外：120秒以下は除く）
    long_videos = [
        v for v in videos
        if v.get("duration_seconds", 0) > 120 and v.get("transcript")
    ]
    sorted_videos = sorted(
        long_videos, key=lambda v: v.get("view_count", 0), reverse=True
    )

    all_clips = []
    for video in sorted_videos[:n_videos]:
        print(f"🔍 分析中: {video['title'][:50]}...")
        clips = suggest_clips(
            video_id=video["video_id"],
            video_title=video["title"],
            transcript=video["transcript"],
            duration_seconds=video.get("duration_seconds", 0),
            n_clips=n_clips_per_video,
        )
        all_clips.extend(clips)
        print(f"  → {len(clips)}個のクリップを提案")

    return all_clips
