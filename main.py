# -*- coding: utf-8 -*-
"""
Google Blogger 자동 포스팅 시스템
- Claude AI로 Vibe Coding 최신 뉴스 수집 및 블로그 포스팅 생성
- SEO 최적화 포함
- Google Blogger API 자동 게시
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── 로깅 설정 ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ── 환경변수 ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
BLOGGER_BLOG_ID     = os.environ["BLOGGER_BLOG_ID"]
GOOGLE_CLIENT_ID    = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REFRESH_TOKEN = os.environ["GOOGLE_REFRESH_TOKEN"]

# 이미지 생성 API (선택, 없으면 텍스트 전용)
IMAGE_API_KEY       = os.environ.get("IMAGE_API_KEY", "")

# ── 설정 ────────────────────────────────────────────────────────────────────────
KST = timezone(timedelta(hours=9))
CLAUDE_MODEL = "claude-sonnet-4-6"  # 최신 Sonnet 사용
MAX_TOKENS   = 8000

# 포스팅 주제 설정 (환경변수로 재정의 가능)
BLOG_TOPIC   = os.environ.get("BLOG_TOPIC", "Vibe Coding")
BLOG_LANG    = os.environ.get("BLOG_LANG", "ko")   # ko | en
BLOG_LABEL   = os.environ.get("BLOG_LABEL", "Vibe Coding,AI,자동화,개발")


# ══════════════════════════════════════════════════════════════════════════════
# 1. Claude API 호출 (웹 검색 + 콘텐츠 생성)
# ══════════════════════════════════════════════════════════════════════════════

def call_claude(system_prompt: str, user_prompt: str, use_search: bool = True) -> str:
    """Claude API 호출 (웹 검색 툴 포함)"""
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    if use_search:
        headers["anthropic-beta"] = "web-search-2025-03-05"

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    if use_search:
        payload["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()

    # 텍스트 블록만 추출
    text_parts = [
        block["text"]
        for block in data.get("content", [])
        if block.get("type") == "text"
    ]
    return "\n".join(text_parts).strip()


# ══════════════════════════════════════════════════════════════════════════════
# 2. 블로그 포스트 생성
# ══════════════════════════════════════════════════════════════════════════════

def generate_blog_post(topic: str, lang: str = "ko") -> dict:
    """Claude로 SEO 최적화 블로그 포스트 생성"""
    now_kst = datetime.now(KST).strftime("%Y년 %m월 %d일 %H시")

    if lang == "ko":
        system = """당신은 SEO 전문가이자 테크 블로거입니다.
최신 뉴스를 검색하여 교육적이고 가독성 높은 한국어 블로그 포스트를 작성합니다.

반드시 다음 JSON 형식으로만 응답하세요 (마크다운 코드블록 없이):
{
  "title": "SEO 최적화 제목 (50-60자)",
  "meta_description": "검색 결과에 표시될 설명 (150-160자)",
  "keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"],
  "content": "HTML 형식의 본문 (h2/h3/p/ul/li 태그 사용, 최소 800자)",
  "summary": "포스트 요약 (2-3문장)"
}"""

        user = f"""[{now_kst}] 주제: {topic}

오늘의 최신 뉴스를 검색하고, 다음 조건으로 블로그 포스트를 작성해주세요:

1. 제목: 독자의 클릭을 유도하는 매력적인 제목
2. 구성: 서론 → 핵심 내용 3-5개 → 실전 팁 → 결론
3. SEO: 자연스럽게 키워드 5회 이상 삽입
4. 가독성: 짧은 문단, 소제목, 불릿 포인트 활용
5. CTA: 마지막에 독자 참여 유도 문구 포함
6. 분량: 최소 800자 이상"""

    else:  # en
        system = """You are an SEO expert and tech blogger.
Search for the latest news and write an educational, high-readability English blog post.

Respond ONLY in this JSON format (no markdown code blocks):
{
  "title": "SEO-optimized title (50-60 chars)",
  "meta_description": "Meta description for search results (150-160 chars)",
  "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
  "content": "HTML body content using h2/h3/p/ul/li tags (min 600 words)",
  "summary": "Post summary (2-3 sentences)"
}"""

        user = f"""[{now_kst}] Topic: {topic}

Search for today's latest news and write a blog post with:
1. Title: Engaging title that drives clicks
2. Structure: Intro → 3-5 key points → Practical tips → Conclusion
3. SEO: Naturally include keywords 5+ times
4. Readability: Short paragraphs, subheadings, bullet points
5. CTA: Reader engagement prompt at the end
6. Length: Minimum 600 words"""

    logger.info(f"📝 Claude로 포스트 생성 중: {topic}")
    raw = call_claude(system, user, use_search=True)

    # JSON 파싱
    try:
        # 혹시 코드블록으로 감싸진 경우 제거
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:])
            cleaned = cleaned.rsplit("```", 1)[0]
        post_data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("JSON 파싱 실패, 기본 구조로 폴백")
        post_data = {
            "title": f"{topic} 최신 트렌드 정리 [{now_kst}]",
            "meta_description": f"{topic}에 관한 오늘의 최신 소식을 정리했습니다.",
            "keywords": [topic, "AI", "자동화", "트렌드", "개발"],
            "content": f"<p>{raw}</p>",
            "summary": raw[:200],
        }

    return post_data


# ══════════════════════════════════════════════════════════════════════════════
# 3. 이미지 생성 (선택)
# ══════════════════════════════════════════════════════════════════════════════

def generate_image(prompt: str, title: str) -> str | None:
    """이미지 생성 API 호출 → base64 또는 URL 반환"""
    if not IMAGE_API_KEY:
        logger.info("IMAGE_API_KEY 없음, 이미지 생성 건너뜀")
        return None

    # ── nanobanan / Stable Diffusion 호환 API ────────────────────────────────
    # 사용하는 API에 맞게 엔드포인트와 페이로드를 수정하세요.
    # 아래는 OpenAI-compatible 이미지 API 예시입니다.
    try:
        resp = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={
                "Authorization": f"Bearer {IMAGE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "dall-e-3",  # 또는 nanobanan2 등 모델명 변경
                "prompt": f"Professional tech blog thumbnail: {prompt}. "
                          "Modern, clean design, vibrant colors, no text.",
                "n": 1,
                "size": "1792x1024",
                "response_format": "url",
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["url"]
    except Exception as e:
        logger.warning(f"이미지 생성 실패: {e}")
        return None


def build_html_with_image(post_data: dict, image_url: str | None) -> str:
    """최종 HTML 콘텐츠 조합 (이미지 + SEO 메타 + 본문)"""
    keywords_str = ", ".join(post_data.get("keywords", []))
    meta_desc = post_data.get("meta_description", "")
    content = post_data.get("content", "")

    image_html = ""
    if image_url:
        image_html = f"""
<div style="text-align:center; margin-bottom:24px;">
  <img src="{image_url}" alt="{post_data['title']}"
       style="max-width:100%; border-radius:12px; box-shadow:0 4px 16px rgba(0,0,0,.15);" />
</div>"""

    return f"""<!-- SEO Meta -->
<!-- <meta name="description" content="{meta_desc}" /> -->
<!-- <meta name="keywords" content="{keywords_str}" /> -->

{image_html}
{content}

<!-- 자동 포스팅: {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} KST -->"""


# ══════════════════════════════════════════════════════════════════════════════
# 4. Google Blogger 게시
# ══════════════════════════════════════════════════════════════════════════════

def get_blogger_service():
    """Google OAuth2 인증 및 Blogger API 서비스 생성"""
    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/blogger"],
    )
    creds.refresh(Request())
    return build("blogger", "v3", credentials=creds, cache_discovery=False)


def publish_to_blogger(title: str, html_content: str, labels: list[str]) -> dict:
    """Blogger에 포스트 게시"""
    service = get_blogger_service()
    post_body = {
        "title": title,
        "content": html_content,
        "labels": labels,
    }
    result = (
        service.posts()
        .insert(blogId=BLOGGER_BLOG_ID, body=post_body, isDraft=False)
        .execute()
    )
    logger.info(f"✅ 게시 완료: {result.get('url')}")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 5. 메인 실행
# ══════════════════════════════════════════════════════════════════════════════

def main():
    logger.info(f"🚀 자동 포스팅 시작 | 주제: {BLOG_TOPIC} | 언어: {BLOG_LANG}")
    start = time.time()

    try:
        # Step 1. 블로그 포스트 생성
        post_data = generate_blog_post(BLOG_TOPIC, BLOG_LANG)
        logger.info(f"📰 제목: {post_data['title']}")

        # Step 2. 이미지 생성 (선택)
        image_url = generate_image(
            prompt=post_data.get("summary", BLOG_TOPIC),
            title=post_data["title"],
        )

        # Step 3. 최종 HTML 빌드
        final_html = build_html_with_image(post_data, image_url)

        # Step 4. Blogger 게시
        labels = [l.strip() for l in BLOG_LABEL.split(",") if l.strip()]
        result = publish_to_blogger(post_data["title"], final_html, labels)

        elapsed = round(time.time() - start, 1)
        logger.info(f"🎉 완료 ({elapsed}s) → {result.get('url')}")

    except Exception as e:
        logger.error(f"❌ 오류 발생: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
