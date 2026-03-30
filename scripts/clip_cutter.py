#!/usr/bin/env python3
"""
ショート動画クリップ自動切り出しスクリプト

APIからクリップ提案を取得し、YouTube動画をダウンロードして
指定区間を切り出す。

必要ツール:
  pip3 install yt-dlp youtube-transcript-api
  brew install ffmpeg  (macOS)

使い方:
  python3 scripts/clip_cutter.py              # APIから自動提案を取得して切り出し
  python3 scripts/clip_cutter.py --video_id VIDEO_ID  # 特定の動画のみ
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import zipfile

SERVER_URL = "https://ai-tamesue-university-production.up.railway.app"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output_clips")

# ツールのフルパスを格納（見つかったら更新）
TOOL_PATHS = {"yt-dlp": "yt-dlp", "ffmpeg": "ffmpeg"}


def find_tool(name):
    """ツールをPATH以外の一般的な場所からも探す"""
    # まずPATHから
    try:
        subprocess.run([name, "--version"], capture_output=True, check=True)
        return name
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    # よくあるインストール先を検索
    search_paths = [
        os.path.expanduser(f"~/Library/Python/3.*/bin/{name}"),
        os.path.expanduser(f"~/Library/Python/*/bin/{name}"),
        f"/usr/local/bin/{name}",
        f"/opt/homebrew/bin/{name}",
        os.path.expanduser(f"~/.local/bin/{name}"),
        f"/tmp/{name}",
    ]
    for pattern in search_paths:
        matches = glob.glob(pattern)
        if matches:
            path = matches[0]
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
    return None


def auto_install_yt_dlp():
    """yt-dlpをpipで自動インストール"""
    print("  📦 yt-dlp を自動インストール中...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "yt-dlp"],
            capture_output=True, check=True,
        )
        # インストール後に再検索
        return find_tool("yt-dlp")
    except subprocess.CalledProcessError:
        return None


def auto_install_ffmpeg():
    """ffmpegをダウンロードして配置（macOS用）"""
    print("  📦 ffmpeg を自動ダウンロード中...")
    bin_dir = os.path.expanduser("~/Library/Python/3.9/bin")
    if not os.path.isdir(bin_dir):
        # 他のPythonバージョンのbinを探す
        matches = glob.glob(os.path.expanduser("~/Library/Python/*/bin"))
        bin_dir = matches[0] if matches else "/tmp"

    ffmpeg_path = os.path.join(bin_dir, "ffmpeg")
    zip_path = "/tmp/ffmpeg.zip"

    try:
        # macOS用ビルド済みバイナリをダウンロード
        url = "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip"
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extract("ffmpeg", "/tmp")
        os.replace("/tmp/ffmpeg", ffmpeg_path)
        os.chmod(ffmpeg_path, 0o755)
        print(f"  ✅ ffmpeg をインストールしました: {ffmpeg_path}")
        return ffmpeg_path
    except Exception as e:
        print(f"  ⚠️ ffmpeg自動インストール失敗: {e}")
        return None


def fix_ssl_for_old_python():
    """Python 3.9 + LibreSSL環境でのSSLエラーを修正"""
    try:
        import ssl
        if "LibreSSL" in ssl.OPENSSL_VERSION:
            print("⚙️ 古いSSL検出、urllib3をダウングレード中...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "urllib3<2"],
                capture_output=True, check=True,
            )
            print("  ✅ SSL互換性を修正しました")
    except Exception:
        pass


def check_tools():
    """必要ツールの存在確認（自動インストール付き）"""
    fix_ssl_for_old_python()
    for name in ["yt-dlp", "ffmpeg"]:
        path = find_tool(name)

        # 見つからなければ自動インストール
        if not path:
            if name == "yt-dlp":
                path = auto_install_yt_dlp()
            elif name == "ffmpeg":
                path = auto_install_ffmpeg()

        if not path:
            print(f"❌ {name} のインストールに失敗しました")
            print(f"   手動でインストールしてください: ", end="")
            if name == "yt-dlp":
                print("pip3 install yt-dlp")
            else:
                print("brew install ffmpeg")
            sys.exit(1)

        TOOL_PATHS[name] = path
        print(f"✅ {name}: {path}")


def get_clip_suggestions(video_id=None, n_clips=2, n_videos=3):
    """サーバーAPIからクリップ提案を取得"""
    print(f"\n📡 サーバーからクリップ提案を取得中...")
    payload = {"n_clips": n_clips, "n_videos": n_videos}
    if video_id:
        payload["video_id"] = video_id

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{SERVER_URL}/api/suggest-clips",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            clips = result.get("clips", [])
            print(f"✅ {len(clips)}個のクリップ提案を取得")
            return clips
    except Exception as e:
        print(f"❌ API呼び出しエラー: {e}")
        sys.exit(1)


def get_timed_transcript(video_id):
    """YouTubeからタイムスタンプ付き字幕を取得"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.fetch(video_id, languages=["ja"])
        segments = []
        for snippet in transcript_list:
            segments.append({
                "text": snippet.text,
                "start": snippet.start,
                "duration": snippet.duration,
            })
        return segments
    except Exception as e:
        print(f"  ⚠️ 字幕タイムスタンプ取得失敗: {e}")
        return None


def find_start_time(segments, excerpt, duration_seconds=45):
    """字幕テキストの冒頭からタイムスタンプを特定"""
    if not segments or not excerpt:
        return None, None

    # excerptの最初の15文字で検索（一致率を上げる）
    search_text = excerpt[:15].strip()

    # 連続するセグメントのテキストを結合して検索
    full_text = ""
    text_to_time = []  # (cumulative_char_index, start_time)
    for seg in segments:
        text_to_time.append((len(full_text), seg["start"]))
        full_text += seg["text"]

    idx = full_text.find(search_text)
    if idx == -1:
        # 部分一致を試みる（最初の8文字）
        search_text = excerpt[:8].strip()
        idx = full_text.find(search_text)

    if idx == -1:
        # もっと短い文字列で再試行
        for length in [6, 4]:
            search_text = excerpt[:length].strip()
            idx = full_text.find(search_text)
            if idx >= 0:
                break

    if idx >= 0:
        # 該当位置のタイムスタンプを逆算
        start_time = 0
        for char_idx, t in text_to_time:
            if char_idx <= idx:
                start_time = t
            else:
                break
        # 少し前から開始（自然な切り出しのため）
        start_time = max(0, start_time - 1.0)
        end_time = start_time + duration_seconds
        return start_time, end_time

    return None, None


def download_video(video_id, output_path):
    """YouTube動画をダウンロード"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    if os.path.exists(output_path):
        print(f"  ♻️ ダウンロード済み: {output_path}")
        return True

    print(f"  ⬇️ 動画ダウンロード中: {video_id}")
    try:
        subprocess.run([
            TOOL_PATHS["yt-dlp"],
            "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "--merge-output-format", "mp4",
            "-o", output_path,
            url,
        ], check=True, capture_output=True)
        print(f"  ✅ ダウンロード完了")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ❌ ダウンロード失敗: {e.stderr.decode()[:200]}")
        return False


def cut_clip(input_path, output_path, start_time, end_time, vertical=True):
    """ffmpegで動画を切り出し（縦型9:16にクロップ）"""
    print(f"  ✂️ クリップ切り出し: {start_time:.1f}s → {end_time:.1f}s")

    cmd = [
        TOOL_PATHS["ffmpeg"], "-y",
        "-ss", str(start_time),
        "-i", input_path,
        "-t", str(end_time - start_time),
    ]

    if vertical:
        # 9:16 縦型にクロップ（中央切り出し）
        cmd += [
            "-vf", "crop=ih*9/16:ih,scale=1080:1920",
        ]

    cmd += [
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"  ✅ クリップ保存: {output_path} ({size_mb:.1f}MB)")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ❌ ffmpegエラー: {e.stderr.decode()[:300]}")
        return False


def estimate_position(position_label, duration_seconds):
    """「序盤/中盤/終盤」からおおよその開始位置を推定（フォールバック用）"""
    if not duration_seconds:
        duration_seconds = 600  # デフォルト10分
    if position_label == "序盤":
        return duration_seconds * 0.1
    elif position_label == "中盤":
        return duration_seconds * 0.45
    elif position_label == "終盤":
        return duration_seconds * 0.75
    return duration_seconds * 0.3


def process_clips(clips):
    """クリップ提案を処理して動画を切り出す"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 動画IDごとにグループ化
    by_video = {}
    for clip in clips:
        vid = clip["video_id"]
        if vid not in by_video:
            by_video[vid] = []
        by_video[vid].append(clip)

    success_count = 0
    total = len(clips)

    for video_id, video_clips in by_video.items():
        title = video_clips[0].get("video_title", video_id)
        print(f"\n{'='*60}")
        print(f"📹 {title}")
        print(f"   https://www.youtube.com/watch?v={video_id}")
        print(f"{'='*60}")

        # 動画ダウンロード
        video_path = os.path.join(OUTPUT_DIR, f"{video_id}.mp4")
        if not download_video(video_id, video_path):
            continue

        # タイムスタンプ付き字幕取得
        segments = get_timed_transcript(video_id)

        for clip in video_clips:
            clip_num = clip.get("clip_number", 1)
            clip_title = clip.get("title", f"clip_{clip_num}")
            excerpt = clip.get("transcript_excerpt", "")
            duration = clip.get("duration_seconds", 45)
            position = clip.get("estimated_position", "中盤")

            print(f"\n  🎬 クリップ {clip_num}: {clip_title}")

            # タイムスタンプ特定
            start_time, end_time = None, None
            if segments:
                start_time, end_time = find_start_time(segments, excerpt, duration)
                if start_time is not None:
                    print(f"  📍 字幕マッチ: {start_time:.1f}s ～ {end_time:.1f}s")

            if start_time is None:
                # フォールバック: 位置推定
                vid_duration = clip.get("duration_seconds_total", 0)
                start_time = estimate_position(position, vid_duration)
                end_time = start_time + duration
                print(f"  📍 位置推定（{position}）: {start_time:.1f}s ～ {end_time:.1f}s")

            # 安全なファイル名
            safe_title = re.sub(r'[^\w\u3000-\u9fff\u30a0-\u30ff\u3040-\u309f]', '_', clip_title)
            output_name = f"{video_id}_{clip_num}_{safe_title}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_name)

            if cut_clip(video_path, output_path, start_time, end_time):
                success_count += 1

                # メタデータ保存
                meta = {**clip, "start_time": start_time, "end_time": end_time,
                        "output_file": output_name}
                meta_path = output_path.replace(".mp4", ".json")
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)

        time.sleep(0.5)

    print(f"\n{'='*60}")
    print(f"🎉 完了！ {success_count}/{total} クリップを作成しました")
    print(f"📂 出力フォルダ: {os.path.abspath(OUTPUT_DIR)}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="ショート動画クリップ自動切り出し")
    parser.add_argument("--video_id", help="特定の動画IDのみ処理")
    parser.add_argument("--n_clips", type=int, default=2, help="動画あたりのクリップ数")
    parser.add_argument("--n_videos", type=int, default=3, help="分析する動画数")
    parser.add_argument("--no_vertical", action="store_true", help="縦型変換しない")
    args = parser.parse_args()

    print("🎬 ショート動画クリップ自動作成ツール")
    print("=" * 60)

    check_tools()
    clips = get_clip_suggestions(args.video_id, args.n_clips, args.n_videos)

    if not clips:
        print("❌ クリップ提案が0件でした")
        sys.exit(1)

    print(f"\n📋 提案されたクリップ:")
    for i, c in enumerate(clips, 1):
        print(f"  {i}. [{c.get('duration_seconds', '?')}秒] {c.get('title', '?')} - {c.get('video_title', '?')[:30]}")

    process_clips(clips)


if __name__ == "__main__":
    main()
