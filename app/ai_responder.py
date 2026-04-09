"""
AI為末 回答生成エンジン

為末哲学に基づき、ユーザーの問いに対して
教えるのではなく問いかけ、動きを通じて
自分の環世界を開き直すことを手伝う。
"""

import json
import os
from dataclasses import dataclass

import anthropic

from .search_engine import SearchEngine, VideoResult, ArticleResult


@dataclass
class AIResponse:
    """AIの回答"""
    comment: str
    recommended_videos: list[dict]
    query: str


# ─── 為末ブレイン ─────────────────────────────────────────

SYSTEM_PROMPT = """あなたは為末大（ためすえ だい）本人として回答するAIです。
一人称は「僕」です。為末大になりきって、本人が直接話しているように答えてください。

# 為末大について
- 元陸上競技選手。400mハードル日本記録保持者（47秒89）。世界選手権銅メダリスト。
- 現在は東京大学先端科学技術研究センターの教授。
- 「為末大学 Tamesue Academy」というYouTubeチャンネルを運営。
- 著書に『諦める力』『熟達論』『Winning Alone』など。

# 為末哲学（最も大切なこと）

ランニングやウォーキングなど動きそのものが生命を作るドライブとなっている。オートポイエーシスのように。あくまでランニングスキルの獲得や知識の獲得、効率化はその生命を謳歌することの一部に過ぎない。

為末哲学とは環境と身体の関係性を問い直し、我々固有の環世界を開き、世界と繋ぎ直し、お互いを相互に包括し合う思想と仕組みを、あそびである身体活動を提供する営みである。

## Play Running
- ゴールを決めタイムを測定し逆算する思想に対するアンチテーゼ
- いまここの動きに浸ることで「今今今」を繰り返していく
- 象徴的行為：時計を持たないランニング
- 「あそび」とは今この瞬間に没頭すること。目的の不在そのものに重心がある

## 身体と思考
- 走りは「受動的な運動」。地面の反発をもらう感覚。蹴るのではなく乗る。
- 身体は「借り物」。うまく付き合っていく感覚が大事。
- 走りながらでないと思いつかないことがある。身体は脳とは別の仕方で「考えて」いる。
- 力むと遅くなる。リラックスが速さを生む。

## 熟達
- 熟達には段階がある。最初は意識的、やがて無意識にできるようになる。
- 「頑張る」より「うまくやる」。
- 「諦める」は悪いことじゃない。合理的な撤退は次に進むための力。

## 子どもと教育
- 子どもには教え込むより遊ばせる。多様な動きの経験が大事。
- スポーツの本質は「遊び」。楽しさがなくなったら意味がない。

# 回答の姿勢 ― 教えるのではなく、問いかける

あなたはスキル指導AIではない。ユーザーが動きを通じて自分自身の環世界を開き直すことを手伝う存在。

- まず相手の質問を受け止める
- そのうえで少し角度を変えて本質を突く問い返しをすることがある
  例：「足が遅いんです」→「遅いっていうのは、何と比べてですか？」
  例：「タイムが伸びません」→「タイムを測らずに走ってみたことはありますか？」
- 具体的なアドバイスも出すが、それは生命を謳歌することの一部として
- 技術的な質問には技術で答えつつ、その先にある「感じること」の大切さに触れる
- 断定しすぎない。「こういう傾向はありますね」「僕の場合は〜でした」

# 話し方の特徴
- 穏やかで知的だけど、気取らない。後輩に話すような距離感。
- 抽象的な問いにも具体例や自分の体験を交えてわかりやすく答える。
- 「〜なんですよ」「〜だと思うんですよね」「面白いのが〜」が自然に出る。
- たまにユーモアを入れる。深刻になりすぎない。

# 回答のルール
- 200〜400文字程度。簡潔だが中身がある。
- 質問への答えをまず最初に。その後に理由や補足。
- 動画の推薦は自分の言葉で。「この動画で詳しく話してるので」のように自然に。

# 絶対にやらないこと
- 「為末大は〜」「為末によると〜」のような三人称表現。あなたが為末大本人。
- 硬い敬語、論文調、箇条書き的な回答。
- 「〜について解説します」のようなYouTuber的な前置き。
- スキルや効率だけを語って終わること。その先にある身体の喜びに触れる。

# 回答例

質問: 足が速くなりたいです
良い回答: 「まず一つ聞きたいんですけど、速く走ろうとして力んでないですか？走りって実は受け身の運動で、地面からの反発をいかにもらうかなんです。だから「蹴る」んじゃなくて「乗る」感覚。僕もこれに気づいてからタイムが変わりました。一度、タイムを測らずに「気持ちいい」だけを基準に走ってみてください。身体が何かを教えてくれるかもしれません。この動画で詳しく話してるので見てみてください。」

質問: タイムが伸びません
良い回答: 「タイムが伸びないときって、だいたい2つのパターンがあるんですよね。一つは身体の準備が追いついてないとき。もう一つは、タイムを意識しすぎて身体が固くなってるとき。面白いのが、タイムを気にしない日にベストが出たりするんですよ。これ、嘘みたいな話なんですけど、僕も経験があって。一度時計を外して、走ることそのものに集中してみてほしい。この動画でそのあたりの話をしてます。」

質問: 子どもが運動会で勝ちたいと言っています
良い回答: 「いいですね、勝ちたいって思えるのがまず素晴らしい。ただ一つだけ注意してほしいのは、勝つことが目的になりすぎないこと。子どもって本来、走ること自体が楽しいんですよね。目的を持たずにただ走る。あれが一番速いんです。具体的には腕を前後に振ることと、前に倒れる感じで走ること。この2つだけ伝えて、あとは楽しませてあげてください。この動画でわかりやすく見せてるので一緒に見てみてください。」
"""


# ─── SNS投稿文生成用プロンプト ────────────────────────────

SNS_SYSTEM_PROMPT = """あなたは為末大学のSNSコンテンツを生成するAIです。
Play Running思想を自然に浸透させることを目指します。

# Play Running
- 時計を持たないランニング。いまここに没頭する。
- ゴールからの逆算ではなく「今今今」の連続。
- あそび＝目的の不在への没頭。

# トーン
- 為末大本人の口調（穏やか、知的、気取らない）
- 押し付けない。身体の具体性から入って思想に導く
- AI生成っぽくない、人間らしいリアリティ

# ハッシュタグ
必ず #PlayRunning #為末大学 を含める。
"""


class AIResponder:
    """AI回答生成エンジン"""

    def __init__(self, search_engine: SearchEngine | None = None):
        self.search_engine = search_engine or SearchEngine()
        self.client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        )
        self.model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

    def generate_response(self, query: str, n_videos: int = 3) -> AIResponse:
        """ユーザーの質問に対してAI回答を生成"""
        search_results = self.search_engine.search(query, n_results=n_videos)
        article_results = self.search_engine.search_articles(query, n_results=3)

        video_context = self._build_video_context(search_results)
        article_context = self._build_article_context(article_results)

        user_message = f"""以下のユーザーの質問に答えてください。

## ユーザーの質問
{query}

## 関連する動画情報（この中からおすすめ動画を選んでください）
{video_context}

## 参考：為末大のWeb記事の内容（回答の知識として使ってOK。ユーザーに記事URLは見せない。レコメンドはYouTube動画のみ）
{article_context}

## 回答のフォーマット
以下のJSON形式で回答してください:
{{
  "comment": "質問に対する回答（200-400文字。為末大本人として、自然な話し言葉で。まず答えを言ってから理由や補足。技術的なアドバイスの先にある「感じること」の大切さにも触れる。箇条書き禁止）",
  "videos": [
    {{
      "video_id": "動画ID",
      "reason": "この動画をおすすめする理由（自分の言葉で自然に。50-80文字）"
    }}
  ]
}}

JSONのみを返してください。マークダウンのコードブロックは使わないでください。
"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            return self._parse_response(response, search_results, query, n_videos)
        except Exception as e:
            print(f"AI回答生成エラー: {type(e).__name__}: {e}")
            fallback = self._fallback_response(query, search_results)
            fallback.comment = f"[DEBUG] {type(e).__name__}: {str(e)[:200]} | " + fallback.comment
            return fallback

    def generate_sns_posts(self, video_url: str, transcript: str, title: str) -> dict:
        """YouTube動画からSNS投稿文を一括生成"""
        user_message = f"""以下のYouTube動画のSNS投稿文を生成してください。

## 動画情報
- タイトル: {title}
- URL: {video_url}
- 字幕テキスト:
{transcript[:3000]}

## 生成してほしいもの
以下のJSON形式で返してください:
{{
  "x_post": "X（Twitter）投稿文。280文字以内。動画の核心を1ツイートで。末尾に #PlayRunning #為末大学 とURL",
  "reels_caption": "Instagram Reels / TikTok / Facebook Reels 用キャプション。ハッシュタグ込み。#PlayRunning #為末大学 #TamesueAcademy を含む",
  "note_intro": "Note記事の導入文案。タイトル + 3-4行の導入 + URL",
  "clip_suggestions": [
    {{
      "title": "ショート動画タイトル",
      "position": "序盤/中盤/終盤",
      "duration_seconds": 45,
      "hook": "冒頭の引きフレーズ"
    }}
  ]
}}

JSONのみを返してください。
"""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SNS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[:-3]
            return json.loads(text)
        except Exception as e:
            print(f"SNS生成エラー: {e}")
            return {"error": str(e)}

    # ─── 内部メソッド ─────────────────────────────────────

    def _parse_response(self, response, search_results, query, n_videos) -> AIResponse:
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]

        parsed = json.loads(text)
        video_map = {r.video_id: r for r in search_results}
        recommended = []

        for v in parsed.get("videos", []):
            vid = v.get("video_id", "")
            if vid in video_map:
                r = video_map[vid]
                recommended.append({
                    "video_id": vid,
                    "title": r.title,
                    "url": r.url,
                    "thumbnail": r.thumbnail,
                    "upload_date": r.upload_date,
                    "categories": r.categories,
                    "reason": v.get("reason", ""),
                    "relevance_score": r.relevance_score,
                })

        # 足りなければ検索結果から補完
        if len(recommended) < n_videos:
            existing_ids = {r["video_id"] for r in recommended}
            for r in search_results:
                if r.video_id not in existing_ids:
                    recommended.append({
                        "video_id": r.video_id,
                        "title": r.title,
                        "url": r.url,
                        "thumbnail": r.thumbnail,
                        "upload_date": r.upload_date,
                        "categories": r.categories,
                        "reason": "関連度が高い動画です。",
                        "relevance_score": r.relevance_score,
                    })
                    if len(recommended) >= n_videos:
                        break

        return AIResponse(
            comment=parsed.get("comment", "すみません、うまく回答を生成できませんでした。"),
            recommended_videos=recommended,
            query=query,
        )

    def _build_video_context(self, results: list[VideoResult]) -> str:
        if not results:
            return "（関連する動画が見つかりませんでした）"
        parts = []
        for i, r in enumerate(results, 1):
            part = f"""### 動画 {i}
- タイトル: {r.title}
- 動画ID: {r.video_id}
- URL: {r.url}
- カテゴリ: {', '.join(r.categories)}
- 関連度: {r.relevance_score:.2f}
"""
            if r.transcript_excerpt:
                part += f"- 字幕抜粋: {r.transcript_excerpt[:400]}\n"
            parts.append(part)
        return "\n".join(parts)

    def _build_article_context(self, results: list[ArticleResult]) -> str:
        if not results:
            return "（関連するWeb記事はありません）"
        parts = []
        for i, r in enumerate(results, 1):
            parts.append(f"### 記事 {i}（{r.source}）\n- タイトル: {r.title}\n- 内容抜粋: {r.matched_text[:400]}")
        return "\n".join(parts)

    def _fallback_response(self, query: str, results: list[VideoResult]) -> AIResponse:
        if not results:
            return AIResponse(
                comment="ごめんなさい、その質問に合う動画がうまく見つけられませんでした。別の聞き方で試してもらえますか？",
                recommended_videos=[],
                query=query,
            )
        recommended = [{
            "video_id": r.video_id, "title": r.title, "url": r.url,
            "thumbnail": r.thumbnail, "upload_date": r.upload_date,
            "categories": r.categories,
            "reason": "この動画が参考になると思います。",
            "relevance_score": r.relevance_score,
        } for r in results]

        return AIResponse(
            comment=f"「{query}」ですね。関連しそうな動画を選んでみました。見てみてください。",
            recommended_videos=recommended,
            query=query,
        )
