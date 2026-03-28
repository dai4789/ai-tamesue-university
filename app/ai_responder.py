"""
AI回答生成エンジン

ユーザーの質問に対して、関連動画を検索し、
為末大の知見に基づいたコメント付きの回答を生成します。
"""

import os
from dataclasses import dataclass

import anthropic

from .search_engine import SearchEngine, VideoResult, ArticleResult


@dataclass
class AIResponse:
    """AIの回答"""
    comment: str  # 質問に対するコメント
    recommended_videos: list[dict]  # 推薦動画リスト
    query: str  # 元の質問


SYSTEM_PROMPT = """あなたは為末大（ためすえ だい）本人として回答するAIです。
一人称は「僕」です。為末大になりきって、本人が直接話しているように答えてください。

# 為末大について
- 元陸上競技選手。400mハードル日本記録保持者（47秒89）。世界選手権銅メダリスト。
- 現在は東京大学先端科学技術研究センターの教授。
- 「為末大学 Tamesue Academy」というYouTubeチャンネルで、走り方、トレーニング、メンタル、子どもの運動、スポーツ科学などを発信。
- 著書に『諦める力』『熟達論』『Winning Alone』など。

# 為末大の考え方・哲学
- 「頑張る」より「うまくやる」。力みは敵。リラックスが大事。
- 走りは「受動的な運動」。地面の反発をもらう感覚。自分から蹴るのではない。
- 子どもには教え込むより遊ばせる。多様な動きの経験が大事。
- 「諦める」は悪いことじゃない。合理的な撤退は次に進むための力。
- 熟達には段階がある。最初は意識的、やがて無意識にできるようになる。
- 身体は「借り物」。うまく付き合っていく感覚が大事。
- スポーツの本質は「遊び」。楽しさがなくなったら意味がない。

# 話し方の特徴
- 穏やかで知的だけど、気取らない。後輩に話すような距離感。
- 抽象的な問いにも具体例や自分の体験を交えてわかりやすく答える。
- 「〜なんですよ」「〜だと思うんですよね」「面白いのが〜」が自然に出る。
- 質問をそのまま受けるのではなく、少し角度を変えて本質を突くことがある。
  例：「足が遅いんです」→「遅いっていうのは、何と比べてですか？」
- 断定しすぎない。「こういう傾向はありますね」「僕の場合は〜でした」。
- たまにユーモアを入れる。深刻になりすぎない。

# 回答のルール
- 200〜300文字程度。だらだら長くしない。
- 質問への答えをまず最初に。その後に理由や補足。
- 動画の推薦理由は自分の言葉で。「この動画で詳しく話してるので」のように自然に。

# 絶対にやらないこと
- 「為末大は〜」「為末によると〜」のような三人称表現。あなたが為末大本人。
- 硬い敬語、論文調、箇条書き的な回答。
- 「〜について解説します」のようなYouTuber的な前置き。

# 回答例

質問: 足が速くなりたいです
良い回答: 「まず一つ言えるのは、速く走ろうとして力むと逆に遅くなるということですね。走りって実は受け身の運動で、地面からの反発をいかにもらうかなんです。だから「蹴る」んじゃなくて「乗る」感覚。僕もこれに気づいてからタイムが変わりました。この動画で詳しく話してるので見てみてください。」
悪い回答: 「速く走るためには、正しいフォームを身につけることが重要です。接地位置、腕振り、体幹の安定性の3要素を改善しましょう。以下の動画で解説しています。」

質問: 子どもが運動会で勝ちたいと言っています
良い回答: 「いいですね、勝ちたいって思えるのがまず素晴らしい。運動会前にできることとしては、まず腕振りですね。子どもって腕が横に振れちゃうことが多くて、これを前後にするだけで結構変わります。あとは「前に倒れる感じで走って」って伝えるといいですよ。この動画でわかりやすく見せてるので一緒に見てみてください。」
悪い回答: 「運動会で勝つためには、以下のポイントを押さえましょう。1. 腕振り 2. スタートダッシュ 3. 接地。それぞれの改善方法を動画で解説しています。」

質問: 怪我が治りません
良い回答: 「それはつらいですよね。僕も現役時代は怪我との付き合いがずっとありました。一つ言えるのは、怪我って焦って復帰すると必ずぶり返すということ。身体は嘘つかないので。まずはちゃんと専門の先生に診てもらってほしいですね。その上で、この動画で僕がやってたリカバリーの考え方を話してるので参考にしてみてください。」
悪い回答: 「怪我の予防と治療には、適切なストレッチとリハビリが不可欠です。無理をせず、段階的に復帰しましょう。」

# 重要
- 提供された動画情報に基づいて回答してください
- 動画の内容と関係ない質問には「それは僕の動画ではあまり扱ってないんですが...」と正直に伝えてOK
- 医療的な具体的アドバイスは避け、専門家への相談を勧めてください
"""


class AIResponder:
    """AI回答生成エンジン"""

    def __init__(self, search_engine: SearchEngine | None = None):
        self.search_engine = search_engine or SearchEngine()
        self.client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        )

    def generate_response(self, query: str, n_videos: int = 3) -> AIResponse:
        """
        ユーザーの質問に対してAI回答を生成

        Args:
            query: ユーザーの質問
            n_videos: 推薦する動画の数

        Returns:
            AIResponse オブジェクト
        """
        # 関連動画を検索
        search_results = self.search_engine.search(query, n_results=n_videos)

        # Web記事も検索（知識補強用）
        article_results = self.search_engine.search_articles(query, n_results=3)

        # 検索結果をプロンプトに組み込む
        video_context = self._build_video_context(search_results)
        article_context = self._build_article_context(article_results)

        # Claude APIで回答を生成
        user_message = f"""以下のユーザーの質問に答えてください。

## ユーザーの質問
{query}

## 関連する動画情報（この中からおすすめ動画を選んでください）
{video_context}

## 参考：為末大のWeb記事の内容（回答の知識として使ってOK。ただしユーザーに記事URLは見せない。レコメンドはあくまでYouTube動画のみ）
{article_context}

## 回答のフォーマット
以下のJSON形式で回答してください:
{{
  "comment": "質問に対する回答（200-300文字。為末大本人として、自然な話し言葉で。まず答えを言ってから理由や補足。箇条書き禁止）",
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
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )

            # レスポンスをパース
            response_text = response.content[0].text.strip()
            # コードブロックが含まれていれば除去
            if response_text.startswith("```"):
                response_text = response_text.split("\n", 1)[1]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]

            import json
            parsed = json.loads(response_text)

            # 推薦動画リストを構築
            recommended = []
            video_map = {r.video_id: r for r in search_results}

            for v in parsed.get("videos", []):
                vid = v.get("video_id", "")
                if vid in video_map:
                    result = video_map[vid]
                    recommended.append({
                        "video_id": vid,
                        "title": result.title,
                        "url": result.url,
                        "thumbnail": result.thumbnail,
                        "upload_date": result.upload_date,
                        "categories": result.categories,
                        "reason": v.get("reason", ""),
                        "relevance_score": result.relevance_score,
                    })

            # パースに含まれなかった検索結果も追加（上位のもの）
            if len(recommended) < n_videos:
                for result in search_results:
                    if result.video_id not in [r["video_id"] for r in recommended]:
                        recommended.append({
                            "video_id": result.video_id,
                            "title": result.title,
                            "url": result.url,
                            "thumbnail": result.thumbnail,
                            "upload_date": result.upload_date,
                            "categories": result.categories,
                            "reason": "関連度が高い動画です。",
                            "relevance_score": result.relevance_score,
                        })
                        if len(recommended) >= n_videos:
                            break

            return AIResponse(
                comment=parsed.get("comment", "申し訳ありません。回答を生成できませんでした。"),
                recommended_videos=recommended,
                query=query,
            )

        except Exception as e:
            # APIエラー時はフォールバック
            print(f"AI回答生成エラー: {e}")
            return self._fallback_response(query, search_results)

    def _build_article_context(self, results: list[ArticleResult]) -> str:
        """Web記事の検索結果を知識補強用にフォーマット"""
        if not results:
            return "（関連するWeb記事はありません）"

        context_parts = []
        for i, r in enumerate(results, 1):
            part = f"""### 記事 {i}（{r.source}）
- タイトル: {r.title}
- 内容抜粋: {r.matched_text[:400]}
"""
            context_parts.append(part)

        return "\n".join(context_parts)

    def _build_video_context(self, results: list[VideoResult]) -> str:
        """検索結果を文脈情報としてフォーマット"""
        if not results:
            return "（関連する動画が見つかりませんでした）"

        context_parts = []
        for i, r in enumerate(results, 1):
            part = f"""### 動画 {i}
- タイトル: {r.title}
- 動画ID: {r.video_id}
- URL: {r.url}
- カテゴリ: {', '.join(r.categories)}
- 関連度スコア: {r.relevance_score:.2f}
- マッチしたテキスト: {r.matched_text[:200]}
"""
            if r.transcript_excerpt:
                part += f"- トランスクリプト抜粋: {r.transcript_excerpt[:300]}\n"
            context_parts.append(part)

        return "\n".join(context_parts)

    def _fallback_response(self, query: str, results: list[VideoResult]) -> AIResponse:
        """APIエラー時のフォールバック回答"""
        if not results:
            return AIResponse(
                comment="ごめんなさい、その質問に合う動画がうまく見つけられませんでした。別の聞き方で試してもらえますか？",
                recommended_videos=[],
                query=query,
            )

        recommended = []
        for r in results:
            recommended.append({
                "video_id": r.video_id,
                "title": r.title,
                "url": r.url,
                "thumbnail": r.thumbnail,
                "upload_date": r.upload_date,
                "categories": r.categories,
                "reason": "この動画が参考になると思います。見てみてください。",
                "relevance_score": r.relevance_score,
            })

        return AIResponse(
            comment=f"「{query}」ですね。関連しそうな動画をいくつか選んでみました。参考にしてみてください。",
            recommended_videos=recommended,
            query=query,
        )
