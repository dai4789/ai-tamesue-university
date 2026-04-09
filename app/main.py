"""
AI為末大学 - メインアプリケーション

FastAPIベースのWebサーバー。
Web API + LINE Bot Webhook + デモUI を提供します。
"""

import os
import json
import hashlib
import hmac
import base64
import time
from pathlib import Path
from contextlib import asynccontextmanager
from collections import defaultdict

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx

from dotenv import load_dotenv

load_dotenv()


# ─── レート制限 ─────────────────────────────────────────
class RateLimiter:
    """シンプルなIPベースレート制限"""
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, client_ip: str) -> bool:
        now = time.time()
        # 古いリクエストを削除
        self._requests[client_ip] = [
            t for t in self._requests[client_ip]
            if now - t < self.window_seconds
        ]
        if len(self._requests[client_ip]) >= self.max_requests:
            return False
        self._requests[client_ip].append(now)
        return True

rate_limiter = RateLimiter(max_requests=10, window_seconds=60)

# ─── アプリ起動時に検索エンジンとAIを初期化 ──────────────
search_engine = None
ai_responder = None


async def _load_videos_background():
    """バックグラウンドで動画データを読み込む"""
    global search_engine, ai_responder
    import asyncio
    from .search_engine import SearchEngine
    from .ai_responder import AIResponder
    from .video_fetcher import fetch_and_update_videos

    # ブロッキング処理を別スレッドで実行
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, fetch_and_update_videos)

    search_engine = SearchEngine()
    ai_responder = AIResponder(search_engine=search_engine)
    print(f"✅ 準備完了 (動画数: {search_engine.total_videos})")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリ起動・終了時の処理"""
    import asyncio

    print("🚀 AI為末大学を起動中...")
    print("📡 サーバーを先に起動し、動画データはバックグラウンドで読み込みます")

    # バックグラウンドタスクとして動画読み込みを開始
    task = asyncio.create_task(_load_videos_background())

    yield

    task.cancel()
    print("👋 AI為末大学を終了")


# ─── FastAPIアプリ ──────────────────────────────────────
app = FastAPI(
    title="AI為末大学",
    description="為末大学 YouTube動画のAIアシスタント",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,      # 本番ではSwagger UIを無効化
    redoc_url=None,      # 本番ではReDocも無効化
)

# セキュリティヘッダー
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# CORS設定（必要なオリジンだけ許可）
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "").split(",")
ALLOWED_ORIGINS = [o.strip() for o in ALLOWED_ORIGINS if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if ALLOWED_ORIGINS else ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# 静的ファイルとテンプレート
BASE_DIR = Path(__file__).parent.parent
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ─── リクエスト/レスポンスモデル ─────────────────────────
class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    n_videos: int = Field(3, ge=1, le=5)


class VideoRecommendation(BaseModel):
    video_id: str
    title: str
    url: str
    thumbnail: str
    upload_date: str = ""
    categories: list[str] = []
    reason: str = ""
    relevance_score: float = 0.0


class AnswerResponse(BaseModel):
    comment: str
    recommended_videos: list[VideoRecommendation]
    query: str


# ─── Web API エンドポイント ──────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """デモUI（トップページ）"""
    total = search_engine.total_videos if search_engine else 0
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"total_videos": total},
    )


@app.post("/api/ask", response_model=AnswerResponse)
async def ask_question(req: QuestionRequest, request: Request):
    """
    質問API

    ユーザーの質問を受け取り、AIコメント + 動画推薦を返します。
    """
    # レート制限チェック
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。少し待ってから再度お試しください。")

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="質問を入力してください")

    if not ai_responder:
        raise HTTPException(status_code=503, detail="サーバー準備中です")

    result = ai_responder.generate_response(
        query=req.question.strip(),
        n_videos=req.n_videos,
    )

    return AnswerResponse(
        comment=result.comment,
        recommended_videos=[
            VideoRecommendation(**v) for v in result.recommended_videos
        ],
        query=result.query,
    )


@app.get("/api/health")
async def health_check():
    """ヘルスチェック"""
    return {"status": "ok"}


@app.get("/api/export-videos")
async def export_videos():
    """動画データをエクスポート（ローカルスクリプト用）"""
    if not search_engine:
        raise HTTPException(status_code=503, detail="動画データ読み込み中です")
    import json as _json
    # transcriptとdescriptionは除外して軽量化
    videos = []
    for v in search_engine._videos:
        videos.append({
            "video_id": str(v.get("video_id", "")),
            "title": str(v.get("title", "")),
            "upload_date": str(v.get("upload_date", "")),
            "duration_seconds": int(v.get("duration_seconds", 0) or 0),
            "view_count": int(v.get("view_count", 0) or 0),
            "url": str(v.get("url", "")),
            "thumbnail": str(v.get("thumbnail", "")),
            "categories": v.get("categories", []),
        })
    return JSONResponse(content=videos)


# ─── SNS投稿文生成 API ────────────────────────────────────

class SNSGenerateRequest(BaseModel):
    video_url: str = Field(..., description="YouTube動画URL")
    title: str = Field("", description="動画タイトル（省略時は自動取得）")


@app.post("/api/generate-sns")
async def generate_sns(req: SNSGenerateRequest, request: Request):
    """
    SNS投稿文一括生成API

    YouTube動画URLから字幕を取得し、
    X / Instagram Reels / TikTok / Note 用の投稿文を生成。
    """
    import asyncio
    import subprocess
    import re

    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="リクエストが多すぎます")

    if not ai_responder:
        raise HTTPException(status_code=503, detail="サーバー準備中です")

    # video_idを抽出
    match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', req.video_url)
    if not match:
        raise HTTPException(status_code=400, detail="有効なYouTube URLを入力してください")
    video_id = match.group(1)

    # 字幕取得（search_engineにあればそちらを使う）
    transcript = ""
    title = req.title
    video_data = search_engine.get_video_details(video_id) if search_engine else None
    if video_data:
        transcript = video_data.get("transcript", "")
        if not title:
            title = video_data.get("title", "")

    # 字幕がなければyt-dlpで取得
    if not transcript:
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, lambda: subprocess.run(
                ["yt-dlp", "--write-auto-sub", "--sub-lang", "ja",
                 "--skip-download", "--sub-format", "vtt",
                 "-o", f"/tmp/sns_{video_id}",
                 f"https://www.youtube.com/watch?v={video_id}"],
                capture_output=True, text=True, timeout=60,
            ))
            vtt_file = f"/tmp/sns_{video_id}.ja.vtt"
            if os.path.exists(vtt_file):
                with open(vtt_file, "r") as f:
                    lines = f.readlines()
                transcript = " ".join(
                    line.strip() for line in lines
                    if line.strip() and not line.startswith(("WEBVTT", "Kind:", "Language:"))
                    and not re.match(r'^\d\d:\d\d', line.strip())
                    and not line.strip().startswith("<")
                    and "align:" not in line
                )
        except Exception as e:
            print(f"字幕取得エラー: {e}")

    if not transcript:
        raise HTTPException(status_code=400, detail="字幕を取得できませんでした")

    if not title:
        title = f"動画 {video_id}"

    # SNS投稿文生成
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: ai_responder.generate_sns_posts(req.video_url, transcript, title),
    )

    return result


# ─── ショート動画クリップ提案 API ─────────────────────────

class ClipSuggestRequest(BaseModel):
    video_id: str | None = Field(None, description="特定の動画IDを指定（省略時は人気動画から自動選択）")
    n_clips: int = Field(3, ge=1, le=5, description="提案するクリップ数")
    n_videos: int = Field(3, ge=1, le=10, description="分析する動画数（video_id省略時）")


@app.post("/api/suggest-clips")
async def suggest_clips_api(req: ClipSuggestRequest, request: Request):
    """
    ショート動画クリップ提案API

    YouTube長尺動画からAIが最適な30-60秒クリップを提案します。
    Instagram Reels / TikTok / YouTube Shorts 向け。
    既に取得済みの字幕データを使用するため、追加のYouTubeリクエスト不要。
    """
    import asyncio
    from .clip_suggester import suggest_clips, suggest_clips_from_library

    if not search_engine:
        raise HTTPException(status_code=503, detail="動画データ読み込み中です。しばらくお待ちください。")

    loop = asyncio.get_event_loop()

    if req.video_id:
        # 特定の動画を分析
        video_data = None
        for v in search_engine._videos:
            if v["video_id"] == req.video_id:
                video_data = v
                break

        if not video_data:
            raise HTTPException(status_code=404, detail="動画が見つかりません")

        if not video_data.get("transcript"):
            raise HTTPException(status_code=400, detail="この動画には字幕データがありません")

        clips = await loop.run_in_executor(
            None,
            lambda: suggest_clips(
                req.video_id,
                video_data["title"],
                video_data["transcript"],
                video_data.get("duration_seconds", 0),
                req.n_clips,
            ),
        )
    else:
        # 人気動画から自動提案
        clips = await loop.run_in_executor(
            None,
            lambda: suggest_clips_from_library(
                search_engine._videos, req.n_videos, req.n_clips,
            ),
        )

    return {
        "total_clips": len(clips),
        "clips": clips,
    }


# ─── LINE Bot Webhook ──────────────────────────────────

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")


def verify_line_signature(body: bytes, signature: str) -> bool:
    """LINE Webhookの署名検証"""
    if not LINE_CHANNEL_SECRET:
        return False
    hash_value = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(hash_value).decode("utf-8")
    return hmac.compare_digest(expected, signature)


async def send_line_reply(reply_token: str, messages: list[dict]):
    """LINE Messaging APIでリプライを送信"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.line.me/v2/bot/message/reply",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            },
            json={
                "replyToken": reply_token,
                "messages": messages,
            },
        )
        if resp.status_code != 200:
            print(f"LINE API Error: {resp.status_code}")


def build_line_flex_message(ai_response) -> dict:
    """AI回答をLINE Flex Messageに変換"""
    # コメント部分
    bubbles = []

    # メインのコメントバブル
    comment_bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "🎓 AI為末大学",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#1a73e8",
                }
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": ai_response.comment,
                    "wrap": True,
                    "size": "sm",
                    "color": "#333333",
                }
            ],
        },
    }
    bubbles.append(comment_bubble)

    # 動画推薦バブル
    for video in ai_response.recommended_videos[:3]:
        video_bubble = {
            "type": "bubble",
            "size": "mega",
            "hero": {
                "type": "image",
                "url": video["thumbnail"],
                "size": "full",
                "aspectRatio": "16:9",
                "aspectMode": "cover",
                "action": {
                    "type": "uri",
                    "uri": video["url"],
                },
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": video["title"][:60],
                        "weight": "bold",
                        "size": "sm",
                        "wrap": True,
                    },
                    {
                        "type": "text",
                        "text": f"📌 {video['reason']}",
                        "size": "xs",
                        "color": "#666666",
                        "wrap": True,
                        "margin": "md",
                    },
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#FF0000",
                        "action": {
                            "type": "uri",
                            "label": "▶ 動画を見る",
                            "uri": video["url"],
                        },
                    }
                ],
            },
        }
        bubbles.append(video_bubble)

    return {
        "type": "flex",
        "altText": f"🎓 AI為末大学: {ai_response.comment[:100]}",
        "contents": {
            "type": "carousel",
            "contents": bubbles,
        },
    }


@app.post("/webhook/line")
async def line_webhook(request: Request):
    """LINE Bot Webhookエンドポイント"""
    body = await request.body()
    signature = request.headers.get("x-line-signature", "")

    # 署名検証
    if LINE_CHANNEL_SECRET and not verify_line_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = json.loads(body)

    for event in data.get("events", []):
        if event["type"] == "message" and event["message"]["type"] == "text":
            user_message = event["message"]["text"]
            reply_token = event["replyToken"]

            # AI回答を生成
            if ai_responder:
                result = ai_responder.generate_response(
                    query=user_message,
                    n_videos=3,
                )

                # Flex Messageを構築
                flex_msg = build_line_flex_message(result)
                await send_line_reply(reply_token, [flex_msg])
            else:
                await send_line_reply(reply_token, [{
                    "type": "text",
                    "text": "申し訳ありません。現在準備中です。しばらくお待ちください。",
                }])

    return JSONResponse(content={"status": "ok"})


# ─── 起動 ────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
    )
