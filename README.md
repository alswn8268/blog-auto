# 🤖 Blog Auto Bot

Claude AI와 GitHub Actions를 활용한 Google Blogger 자동 포스팅 시스템입니다.
매일 최신 뉴스를 검색하여 SEO 최적화된 블로그 포스트를 자동으로 생성하고 게시합니다.

---

## ✨ 주요 기능

- **자동 포스팅**: 하루 2회(오전 9시, 오후 9시 KST) 자동 실행
- **최신 뉴스 반영**: Claude 웹 검색으로 오늘의 뉴스를 바탕으로 글 생성
- **다국어 지원**: 한국어 / 영어 블로그 동시 운영
- **다중 블로그**: 한국어 · 영어 · 재테크 등 블로그별 개별 설정
- **SEO 최적화**: 제목, 메타 설명, 키워드 자동 생성
- **수동 실행**: GitHub Actions에서 주제 직접 입력 후 즉시 실행 가능

---

## 🗂️ 파일 구조

```
blog-auto-bot/
├── main.py                          # 핵심 자동화 스크립트
├── requirements.txt                 # 필요한 라이브러리 목록
└── .github/
    └── workflows/
        └── daily_post.yml           # GitHub Actions 스케줄 설정
```

> `get_token.py`는 Google Refresh Token 최초 발급용으로 로컬에만 보관합니다.

---

## ⚙️ 동작 방식

```
GitHub Actions 스케줄 트리거
        ↓
Claude AI (웹 검색 + 포스트 생성)
        ↓
SEO 최적화 HTML 콘텐츠 조합
        ↓
Google Blogger API로 자동 게시
```

---

## 🚀 설치 및 설정

### 1. 필요한 계정 및 API 키

| 항목 | 발급처 |
|------|--------|
| Anthropic API Key | [console.anthropic.com](https://console.anthropic.com) |
| Google Cloud OAuth2 (Client ID / Secret) | [console.cloud.google.com](https://console.cloud.google.com) |
| Google Refresh Token | 로컬에서 `get_token.py` 실행 |
| Blogger Blog ID | 블로그 URL 또는 Blogger 설정에서 확인 |

### 2. GitHub Secrets 등록

저장소 → **Settings → Secrets and variables → Actions** 에서 아래 값을 등록합니다.

| Secret 이름 | 설명 |
|-------------|------|
| `ANTHROPIC_API_KEY` | Claude API 키 |
| `GOOGLE_CLIENT_ID` | Google OAuth2 클라이언트 ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth2 클라이언트 시크릿 |
| `BLOGGER_BLOG_ID_KO` | 한국어 블로그 ID |
| `BLOGGER_BLOG_ID_EN` | 영어 블로그 ID |
| `BLOGGER_BLOG_ID_FIN` | 재테크 블로그 ID |
| `GOOGLE_REFRESH_TOKEN_KO` | 한국어 블로그용 Refresh Token |
| `GOOGLE_REFRESH_TOKEN_EN` | 영어 블로그용 Refresh Token |
| `GOOGLE_REFRESH_TOKEN_FIN` | 재테크 블로그용 Refresh Token |

### 3. Google Refresh Token 발급

```bash
pip install google-auth-oauthlib
python get_token.py
```

브라우저에서 Google 계정 로그인 → 권한 허용 → 터미널에 출력된 토큰을 Secrets에 등록

---

## ⏰ 실행 스케줄

| 실행 시각 (KST) | 실행 내용 |
|----------------|-----------|
| 매일 오전 9시 | 한국어 포스팅 → 영어 포스팅 → 재테크 포스팅 |
| 매일 오후 9시 | 한국어 포스팅 → 영어 포스팅 |

### 수동 실행

GitHub → **Actions → 자동 블로그 포스팅 → Run workflow**
주제와 언어를 직접 입력하여 즉시 실행할 수 있습니다.

---

## 🛠️ 기술 스택

- **AI**: Claude Sonnet (Anthropic) — 웹 검색 + 콘텐츠 생성
- **자동화**: GitHub Actions
- **블로그 플랫폼**: Google Blogger API v3
- **인증**: Google OAuth2

---

## ⚠️ 주의사항

- Anthropic API는 **유료**입니다. 크레딧 잔액을 주기적으로 확인하세요.
- GitHub 저장소가 **60일 이상 비활성** 상태면 스케줄이 자동 중지될 수 있습니다.
- `get_token.py`에는 OAuth2 인증 정보가 포함되어 있으므로 **절대 GitHub에 업로드하지 마세요**.
