# 사규·법령 통합 검색 시스템(Q&A 기반) — 기술 명세서

> 한국언론진흥재단 AX 공모전 프로토타입 · 작성 기준일 2026-08-11
> 이 문서는 지금까지 논의한 내용을 전체 재검토 형태로 통합하고, 각 레이어에 실제 구현 코드 수준의 세부사항을 추가한 버전입니다.

---

## 0. 프로젝트 개요

**문제 정의**: 사규·법령은 조항이 많고 개정이 잦아, 필요한 규정을 그때그때 찾기 어렵다. 담당자에게 직접 물어보거나 원문을 처음부터 훑어야 하는 비효율이 발생한다.

**해결 방향**: 사규·법령 원문을 조항 단위로 색인하고, 자연어 질문에 대해 근거 조항을 인용하며 답하는 RAG(검색 증강 생성) 기반 Q&A 시스템을 구축한다.

**제약 조건**
| 항목 | 내용 |
|---|---|
| 운영 환경 | 내부망 전용, 외부 클라우드 API 의존 최소화 |
| 개발 기간 | 약 1개월 (시연 가능한 프로토타입 수준) |
| 개발 인력 | 기본 코딩 역량 보유 1인 |
| 기술 스택 | 무료 오픈소스 우선 |
| 플랫폼 | 웹 (그룹웨어 임베드 고려) |
| 시연 형태 | 로컬 구동 웹/앱이면 충분(클라우드·앱스토어 배포 불필요), AI로 작성한 코드 형태(예: 엑셀 VBA)도 인정 |

**확보 예정 데이터**: 공시 규정 원문 파일 일체(HWP/PDF), 파일명·제개정일 표기 규칙, 직원이 직접 만들어 운영 중인 Q&A 데이터. 이 세 가지는 각각 2.1(HWP 파싱 검증), 2.1의 파일명 메타데이터 추출·4.4(시행일자), 3장(RAGAS 골든셋)에 바로 반영됩니다.

**참고**: GOAD 안내봇(위즈넛 기반)과의 하이브리드 연동 아이디어는 별도로 논의 중이며, 이 문서에서는 부록으로만 남겨두고 본문에서는 다루지 않습니다.

---

## 1. 전체 아키텍처

```
[원문: HWP·PDF·DOCX]
      │ 파싱
      ▼
[조항 단위 청킹 + 메타데이터 태깅]
      │ 임베딩(BGE-M3)
      ▼
[Qdrant 벡터DB 색인]
      │
(질문 입력) ──► [하이브리드 검색] ──► [리랭커] ──► [LLM 생성] ──► [Streamlit UI]
                                                        │
                                              근거 조항 인용 + 신뢰도 배지
```

---

## 2. 레이어별 구현 세부사항

### 2.1 문서 처리 — HWP/HWPX 파싱

1순위로 `rhwp`의 LangChain 연동 로더를 사용합니다. HWP/HWPX를 모두 지원하고 속도가 빠릅니다.

```python
# loaders/hwp_loader.py
from rhwp.integrations.langchain import HwpLoader

def load_hwp(filepath: str):
    loader = HwpLoader(filepath)
    return loader.load()  # LangChain Document 객체 리스트 반환
```

> 참고: `rhwp`는 비교적 최근 공개된 패키지라 API가 바뀔 수 있습니다. 실제 사용 전 PyPI/GitHub의 최신 사용법을 한 번 더 확인하세요.

대안(순수 Python, JVM·Windows 불필요)으로 `hwp-hwpx-parser`도 함께 시도해보고 결과가 더 깨끗한 쪽을 채택하는 걸 권장합니다.

```python
from hwp_hwpx_parser import Reader

def load_hwp_fallback(filepath: str) -> dict:
    with Reader(filepath) as r:
        return {
            "text": r.extract_text(),
            "tables": r.get_tables_as_markdown(),
        }
```

**파일명 기반 메타데이터 추출**: 파일명·제개정일 표기 규칙을 받으면, 본문을 파싱하지 않고도 파일명만으로 시행일자를 뽑아낼 수 있습니다. 아래는 "문서명(YYYY.MM.DD. 개정구분).hwp" 형태를 가정한 예시이며, 실제 표기 규칙을 확인한 뒤 정규식만 그 형식에 맞게 교체하면 됩니다.

```python
# metadata/filename_parser.py
import re

# 예시: "인사규정(2024.03.15. 일부개정).hwp" — 실제 규칙 확인 후 정규식 교체
FILENAME_PATTERN = re.compile(
    r'(?P<doc_title>[^()_]+)'
    r'[(_]\s*(?P<year>\d{4})[.\-]?(?P<month>\d{2})[.\-]?(?P<day>\d{2})\.?\s*'
    r'(?P<revision_type>제정|전부개정|일부개정|개정)?'
)

def parse_filename_metadata(filename: str) -> dict:
    m = FILENAME_PATTERN.search(filename)
    if not m:
        return {"doc_title": filename, "effective_date": None, "revision_type": None}
    y, mo, d = m.group("year"), m.group("month"), m.group("day")
    return {
        "doc_title": m.group("doc_title").strip(),
        "effective_date": f"{y}-{mo}-{d}",
        "revision_type": m.group("revision_type") or "미상",
    }
```

이렇게 뽑은 `effective_date`는 문서 처리일이 아니라 실제 시행일자이므로, 4.4의 자동 재색인에서 바로 사용합니다.

### 2.2 조항 구조 인식 청킹

법령·사규 특유의 `제n조`, `제n항` 구조를 정규식으로 인식해, 조 단위를 1차 청크로 삼습니다.

```python
# chunking/article_splitter.py
import re

ARTICLE_PATTERN = re.compile(r'(제\s*\d+\s*조(?:의\s*\d+)?)\s*(\([^)]+\))?')

def split_by_article(text: str, doc_title: str, parent_section: str = "") -> list[dict]:
    """조 단위로 분할하고 각 조각에 메타데이터를 붙인다."""
    matches = list(ARTICLE_PATTERN.finditer(text))
    chunks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunks.append({
            "article_no": m.group(1).strip(),
            "article_title": (m.group(2) or "").strip("()"),
            "text": text[start:end].strip(),
            "doc_title": doc_title,
            "parent_section": parent_section,
        })
    return chunks
```

표·부칙·별지서식은 이 정규식만으로는 깨질 수 있으니, 1주차에 실제 샘플 문서로 반드시 검증하세요.

### 2.3 임베딩 — BGE-M3

```python
# embedding/embedder.py
from FlagEmbedding import BGEM3FlagModel

model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)

def embed_texts(texts: list[str]):
    out = model.encode(texts, return_dense=True, return_sparse=True)
    return out['dense_vecs'], out['lexical_weights']  # 의미검색 + 키워드검색 동시 지원
```

### 2.4 벡터 DB — Qdrant 스키마 설계

메타데이터(payload) 필드를 처음부터 잘 설계해두면, 이후 조항충돌탐지·개정이력추적 기능을 붙이기 쉬워집니다.

| 필드 | 용도 |
|---|---|
| `doc_type` | "사규" \| "법령" \| "판례" — 도메인별 라우팅에 사용 |
| `doc_title` | 문서명 (예: "인사규정") |
| `article_no` | 조 번호 (예: "제15조") |
| `parent_section` | 소속 장/절 |
| `effective_date` | 시행일자 — 개정이력추적 기능의 핵심 필드 |
| `superseded_by` | 최신본 여부/후속 버전 참조 |
| `source_file` | 원본 파일 경로 |

```python
# vectordb/setup.py
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

client = QdrantClient(host="localhost", port=6333)

client.create_collection(
    collection_name="gyu_law_articles",
    vectors_config=VectorParams(size=1024, distance=Distance.COSINE),  # bge-m3 dense 차원
)
```

### 2.5 리랭커

```python
# rerank/reranker.py
from FlagEmbedding import FlagReranker

reranker = FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=True)

def rerank(query: str, candidates: list[str]) -> list[float]:
    pairs = [[query, c] for c in candidates]
    return reranker.compute_score(pairs)
```

> 한국어 특화 체크포인트(`bge-reranker-v2-m3-ko`)가 별도로 배포되어 있다면 그쪽을 우선 시도하세요. 정확한 리포지토리 경로는 HuggingFace에서 최신 상태로 확인이 필요합니다.

### 2.6 LLM — Ollama 연동 + 프롬프트 템플릿

프롬프트에서 가장 중요한 두 가지는 **근거 조항 강제 인용**과 **모르면 모른다고 답하게 하는 것**입니다.

```python
# llm/generate.py
import requests

SYSTEM_PROMPT = """당신은 한국언론진흥재단의 사규·법령 안내 도우미입니다.
반드시 아래 [근거 조항]에 명시된 내용만을 근거로 답변하세요.
[근거 조항]에 없는 내용은 "확인되지 않습니다"라고 답하고 추측하지 마세요.
답변 마지막 줄에는 반드시 근거로 사용한 조항 번호를 나열하세요.
"""

def ask_llm(question: str, contexts: list[dict], model: str = "qwen3:8b") -> str:
    context_text = "\n\n".join(
        f"[{c['doc_title']} {c['article_no']}]\n{c['text']}" for c in contexts
    )
    prompt = f"{SYSTEM_PROMPT}\n\n[근거 조항]\n{context_text}\n\n[질문]\n{question}"
    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
    )
    return resp.json()["response"]
```

### 2.7 오케스트레이션 — LangChain 파이프라인

```python
# pipeline/build_index.py
from langchain_community.vectorstores import Qdrant
from langchain_community.embeddings import HuggingFaceEmbeddings

embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")

vectorstore = Qdrant.from_documents(
    documents=chunked_docs,          # 2.2에서 만든 청크를 Document로 변환한 것
    embedding=embeddings,
    url="http://localhost:6333",
    collection_name="gyu_law_articles",
)

retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
```

### 2.8 프론트엔드 — Streamlit 스켈레톤

```python
# app/main.py
import streamlit as st

st.title("사규·법령 Q&A")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if question := st.chat_input("궁금한 규정을 물어보세요"):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    contexts = retriever.get_relevant_documents(question)
    answer = ask_llm(question, contexts)

    with st.chat_message("assistant"):
        st.markdown(answer)
        with st.expander("근거 조항 보기"):
            for c in contexts:
                st.caption(f"{c.metadata['doc_title']} {c.metadata['article_no']}")
                st.text(c.page_content)

    st.session_state.messages.append({"role": "assistant", "content": answer})
```

### 2.9 배포 — Docker Compose

```yaml
version: "3.8"
services:
  qdrant:
    image: qdrant/qdrant
    ports: ["6333:6333"]
    volumes: ["./qdrant_data:/qdrant/storage"]

  ollama:
    image: ollama/ollama
    ports: ["11434:11434"]
    volumes: ["./ollama_data:/root/.ollama"]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  app:
    build: ./app
    ports: ["8501:8501"]
    depends_on: [qdrant, ollama]
```

---

## 3. 평가 체계 — RAGAS

직원이 이미 만들어 운영 중인 Q&A 데이터가 있다면, 골든셋을 처음부터 새로 만들 필요 없이 이걸 변환해서 씁니다.

```python
# eval/build_golden_set.py
import json

def load_existing_qa(filepath: str) -> list[dict]:
    """직원이 만든 운영 Q&A 데이터를 골든셋 포맷으로 변환한다"""
    with open(filepath, encoding="utf-8") as f:
        raw_qa = json.load(f)  # 실제 파일 형식(엑셀/CSV 등)에 맞게 조정 필요

    return [{"question": item["질문"], "ground_truth": item["답변"]} for item in raw_qa]
```

다만 그대로 쓰기 전에 두 가지는 꼭 확인하세요.
- **지금도 유효한 답변인가**: 그 사이 조항이 개정됐다면 답변도 같이 갱신해야 합니다.
- **질문 표현이 실제 사용자 말투와 비슷한가**: 운영 Q&A는 보통 정제된 문어체라, 실제 채팅창에 들어올 법한 구어체 질문 몇 개는 별도로 추가하는 걸 권장합니다.

```python
# eval/run_ragas.py
from ragas import evaluate
from ragas.metrics import faithfulness, context_recall
from datasets import Dataset

golden_set = Dataset.from_dict({
    "question": [...],     # load_existing_qa() 결과 + 직접 추가한 구어체 질문
    "answer": [...],       # 시스템이 생성한 답변
    "contexts": [...],     # 검색된 근거 조항
    "ground_truth": [...], # load_existing_qa()의 답변 (필요시 최신화)
})

result = evaluate(golden_set, metrics=[faithfulness, context_recall])
print(result)  # 예: {'faithfulness': 0.82, 'context_recall': 0.77}
```

목표치: Faithfulness 0.75 이상. 이 아래로 나오면 청킹·프롬프트를 먼저 의심하세요.

---

## 4. 차별화 기능 구현 로직

### 4.1 조항 간 충돌 탐지

```python
# features/conflict_detect.py
from itertools import combinations
from numpy import dot
from numpy.linalg import norm

def cosine_sim(a, b):
    return dot(a, b) / (norm(a) * norm(b))

def find_conflict_candidates(articles: list[dict], low=0.70, high=0.85):
    """유사도는 높지만 완전히 같지는 않은 조항 쌍만 후보로 추출"""
    candidates = []
    for a, b in combinations(articles, 2):
        sim = cosine_sim(a["embedding"], b["embedding"])
        if low <= sim <= high:
            candidates.append((a["article_no"], b["article_no"], sim))
    return candidates
# 이후 후보 쌍을 LLM에 배치로 "실질적으로 상충하는가?" 판단시켜 사전 저장
```

### 4.2 개정 이력 diff

```python
# features/revision_diff.py
import difflib

def diff_articles(old_text: str, new_text: str) -> str:
    diff = difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(),
        lineterm="", fromfile="개정 전", tofile="개정 후",
    )
    return "\n".join(diff)
```

### 4.3 신뢰도 점수

```python
# features/confidence.py
def compute_confidence(rerank_score: float, faithfulness_score: float) -> str:
    combined = 0.5 * rerank_score + 0.5 * faithfulness_score
    if combined >= 0.8:
        return "상"
    elif combined >= 0.5:
        return "중"
    return "하"
```

### 4.4 조항 개정 자동 감지 및 재색인

사규 개정 공지가 나올 때마다 사람이 수동으로 다시 색인하는 게 아니라, 파일 변경을 감지해 바뀐 조항만 자동으로 갱신하는 파이프라인입니다. 4.2의 diff 로직을 그대로 재사용해서 "실제로 내용이 바뀐 조항"만 골라내는 게 핵심입니다.

```python
# features/auto_reindex.py
import hashlib
from pathlib import Path
from datetime import datetime

def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def detect_changed_files(watch_dir: Path, hash_store: dict) -> list[Path]:
    """이전에 기록해둔 해시와 비교해 변경된 파일만 골라낸다"""
    changed = []
    for f in watch_dir.glob("*.hwp"):
        h = file_hash(f)
        if hash_store.get(str(f)) != h:
            changed.append(f)
            hash_store[str(f)] = h
    return changed

def reindex_changed_file(filepath: Path, qdrant_client, embed_fn):
    # 0. 파일명 규칙에서 실제 시행일자 추출 (2.1의 parse_filename_metadata 재사용)
    meta = parse_filename_metadata(filepath.name)
    effective_date = meta["effective_date"] or datetime.now().strftime("%Y-%m-%d")

    # 1. 재파싱 + 재청킹
    text = load_hwp_fallback(str(filepath))["text"]
    new_chunks = split_by_article(text, doc_title=filepath.stem)

    # 2. 기존 조항과 비교해 "진짜 바뀐" 조항만 추림 (4.2 diff 재사용)
    old_chunks = fetch_current_articles(qdrant_client, doc_title=filepath.stem)
    changed = []
    for new in new_chunks:
        old = next((o for o in old_chunks if o["article_no"] == new["article_no"]), None)
        if old is None or old["text"] != new["text"]:
            changed.append((old, new))

    # 3. 변경분만 재임베딩 + upsert, 기존본은 superseded 처리(이력 보존)
    for old, new in changed:
        if old:
            mark_superseded(qdrant_client, old["id"], superseded_by=new["article_no"], until=effective_date)
        vec, _ = embed_fn([new["text"]])
        upsert_article(qdrant_client, new, vector=vec[0], effective_date=effective_date)

    return len(changed)
```

**설계 포인트 네 가지**
- 파일 전체가 아니라 **조항 단위로 변경 여부를 비교**하므로, 문서 하나에 조항이 100개 있어도 실제로 바뀐 2~3개만 재임베딩합니다. 임베딩은 계산 비용이 있어 이 최적화가 실제로 체감됩니다.
- 기존 조항을 삭제하지 않고 `superseded_by`로 표시만 하기 때문에, 개정 이력 추적 기능(4.2)과 데이터가 자연스럽게 이어집니다.
- `effective_date`가 처리 시점이 아니라 **파일명에서 뽑은 실제 시행일자**이기 때문에, 개정이력추적 결과가 실제 규정 이력과 정확히 맞아떨어집니다. 이전 버전(처리일 기준)의 가장 큰 약점이 해결된 부분입니다.
- 트리거 방식은 상황에 맞춰 고르면 됩니다.

| 트리거 방식 | 적합한 상황 |
|---|---|
| cron 스케줄(예: 매일 새벽 3시) | 구현이 가장 쉬움, 1개월 프로토타입엔 이 정도로 충분 |
| `watchdog` 파일시스템 감시 | 개정 반영을 거의 실시간으로 하고 싶을 때 |
| 그룹웨어 게시판 API/webhook | 6.1의 그룹웨어 연동과 자연스럽게 결합 |

### 4.5 로그 기반 서비스 개선 루프

로그를 감사 목적으로만 쓰지 않고, 서비스가 스스로 나아지는 데이터로 순환시킬 수 있습니다. 세 가지 활용 경로입니다.

**1) 저신뢰 질문 클러스터링 → 문서 공백 발견**

```python
# improvement/gap_analysis.py
import json

def find_low_confidence_questions(log_path: str) -> list[str]:
    """confidence가 '하'인 질문만 모은다. 실제로는 임베딩 후 클러스터링해서
    주제별로 묶는 것을 권장한다."""
    results = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            if entry["confidence"] == "하":
                results.append(entry["question"])
    return results
```

이 결과를 관리자 화면에 "이런 질문이 반복되는데 관련 문서가 부족합니다"로 보여주면, 어떤 사규를 다음에 색인해야 할지 우선순위가 자연히 정해집니다.

**2) 사용자 피드백(👍/👎) → 골든셋 자동 확장**

```python
col1, col2 = st.columns(2)
if col1.button("👍", key=f"up_{msg_id}"):
    log_feedback(msg_id, "positive")
if col2.button("👎", key=f"down_{msg_id}"):
    log_feedback(msg_id, "negative")
```

👍를 받은 고신뢰 답변은 사람이 한 번 검수한 뒤 3장 RAGAS 골든셋에 추가 후보로 올리고, 👎를 받은 답변은 검토 큐로 보내 프롬프트·청킹 개선의 재료로 씁니다. 골든셋이 실제 사용 데이터로 계속 자라나는 구조가 됩니다.

**3) 버전 태깅으로 회고적 비교**

로그에 `prompt_version`, `model_version` 필드를 추가해두면, "프롬프트를 바꾸기 전/후 신뢰도 평균이 어떻게 달라졌는지"를 나중에 로그만으로 되짚어볼 수 있습니다.

> 다만 이 순환 구조가 성립하려면 질문·답변 로그를 충분히, 오래 갖고 있어야 합니다. 이게 바로 6.2에서 다시 짚는 개인정보 보호 관점의 가장 취약한 지점입니다.

---

## 5. 1개월 실행 로드맵

| 주차 | 핵심 작업 | 리스크 |
|---|---|---|
| 1주차 | HWP 파서 3종 비교, 조항 청킹 규칙 검증, GPU 서버 스펙 확인 | 가장 중요 — 여기서 막히면 전체 일정 흔들림 |
| 2주차 | 임베딩+벡터DB 색인, 골든셋 20~30문항으로 Recall 테스트 | 청킹 품질이 곧 검색 품질 |
| 3주차 | LLM 연동, 프롬프트 엔지니어링, 리랭커 적용 | "모르면 모른다" 정책 튜닝에 시간 소요 가능 |
| 4주차 | Streamlit UI, 차별화 기능 1~2개 완성, Docker 패키징, 리허설 | 4개 다 하려 하지 말고 1~2개는 완성도 있게 |

원문·파일명 규칙·기존 Q&A 데이터가 실제로 들어오면 1주차 리스크(파서 검증)와 2주차 리스크(골든셋 제작)가 동시에 낮아집니다 — 확보되는 대로 이 세 가지부터 가장 먼저 시험해보세요.

---

## 6. 확장 항목 (그룹웨어 · 보안 · GOAD)

### 6.1 그룹웨어 연동

위젯/임베드 삽입(사용률에 가장 큰 영향) → SSO 연동(LDAP/SAML) → 게시판 변경 감지를 4.4의 자동 재색인 트리거로 연결.

### 6.2 보안 강화

네 개 계층으로 나눠서 설계했습니다.

**네트워크 계층**: 내부망 전용 배포, 방화벽에서 사내 IP 대역만 허용, 외부 노출 구간은 리버스 프록시(Nginx)에서 TLS 종료 후 내부로는 평문 전달.

**애플리케이션 계층 — RBAC(역할 기반 접근 제어)**: 부서별로 열람 가능한 문서 범위를 다르게 합니다. Qdrant는 검색 시점에 메타데이터 필터를 걸 수 있어서, 별도 접근제어 서버 없이도 구현 가능합니다.

```python
# security/rbac.py
from qdrant_client.models import Filter, FieldCondition, MatchAny

ROLE_DOC_TYPE_MAP = {
    "인사팀": ["인사규정", "복무규정", "일반사규", "법령"],
    "전체직원": ["일반사규", "법령"],
}

def get_user_role(request) -> str:
    # 사내 SSO가 발급한 세션/JWT에서 부서 클레임을 읽는다
    return request.headers.get("X-User-Dept", "전체직원")

def build_permission_filter(role: str) -> Filter:
    allowed = ROLE_DOC_TYPE_MAP.get(role, ROLE_DOC_TYPE_MAP["전체직원"])
    return Filter(must=[FieldCondition(key="doc_type", match=MatchAny(any=allowed))])

# 검색 시 적용
results = qdrant_client.search(
    collection_name="gyu_law_articles",
    query_vector=query_vec,
    query_filter=build_permission_filter(get_user_role(request)),
    limit=5,
)
```

**데이터 계층 — 감사 로그**: 전자정부법 기반 정보시스템 감리나 개인정보 처리방침 현행화 점검 때, "AI가 어떤 근거로 어떤 답을 줬는지" 그대로 추적 자료로 쓸 수 있습니다.

> **점검 결과**: 이전 버전은 `question`·`answer`를 마스킹 없이 그대로 저장하고, `user_id`도 실명 그대로 남기며, 보존기간도 정해두지 않았습니다. 감사로그 자체가 개인정보 처리 행위이기 때문에 이 세 가지는 구조적 결함입니다. 아래는 수정된 버전입니다.

```python
# security/audit_log.py
import hashlib
import json
from datetime import datetime, timedelta
from security.pii_mask import mask_pii  # 아래 "개인정보 마스킹" 절 참고

SALT = "환경변수로_관리할_임의값"  # 실제로는 os.environ에서 읽어오는 걸 권장

def pseudonymize(user_id: str) -> str:
    """로그에는 실명 대신 단방향 해시만 남긴다.
    감사 등 실명 복원이 꼭 필요한 경우에는 사번-해시 매핑 테이블을 별도로,
    감사로그보다 더 엄격한 접근권한으로 보관한다."""
    return hashlib.sha256(f"{user_id}-{SALT}".encode()).hexdigest()[:16]

def log_qa_event(user_id: str, question: str, answer: str, sources: list[str], confidence: str):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "user_id": pseudonymize(user_id),
        "question": mask_pii(question),
        "answer": mask_pii(answer),
        "sources": sources,
        "confidence": confidence,
    }
    with open("logs/qa_audit.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

RETENTION_DAYS = 90  # 재단 개인정보 처리방침 상 보유기간에 맞춰 조정

def purge_old_logs(log_path: str = "logs/qa_audit.jsonl"):
    """보존기간이 지난 로그를 지체 없이 파기한다. cron으로 매일 실행."""
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    kept = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            if datetime.fromisoformat(json.loads(line)["timestamp"]) >= cutoff:
                kept.append(line)
    with open(log_path, "w", encoding="utf-8") as f:
        f.writelines(kept)
```

`ensure_ascii=False`를 꼭 넣어야 로그 파일에서도 한글이 깨지지 않고 그대로 저장됩니다. 로그 파일 자체도 개인정보이므로, RBAC과 별개로 `logs/` 디렉터리 접근권한을 관리자로 제한하세요.

**개인정보 처리방침 갱신 검토**: 이 시스템은 질문 로그 수집이라는 새로운 개인정보 처리를 추가하므로, 재단의 개인정보 처리방침에 이 처리가 반영되어 있는지 확인이 필요합니다. 4.5처럼 로그를 서비스 개선(원래 목적인 감사와는 다른 목적)에 쓰려면, 그 목적이 처리방침에 명시되어 있는지도 함께 검토해야 합니다.

**데이터 계층 — 개인정보 마스킹**: 질문에 개인정보가 섞여 들어오는 경우(예: "OOO 직원 연봉이...")를 1차로 정규식 필터링합니다.

```python
# security/pii_mask.py
import re

PII_PATTERNS = {
    "주민등록번호": re.compile(r'\d{6}-\d{7}'),
    "전화번호": re.compile(r'01\d-\d{3,4}-\d{4}'),
    "이메일": re.compile(r'[\w.-]+@[\w.-]+\.\w+'),
}

def mask_pii(text: str) -> str:
    for name, pattern in PII_PATTERNS.items():
        text = pattern.sub(f"[{name} 마스킹됨]", text)
    return text
```

정규식은 형식이 정해진 정보(주민번호, 전화번호)에는 효과적이지만, 이름·직급처럼 문맥으로만 판단되는 정보는 놓칩니다. 정확도를 더 높이려면 NER(개체명인식) 모델을 2차 필터로 추가하는 걸 고도화 과제로 남겨두는 게 현실적입니다.

**애플리케이션 계층 — 프롬프트 인젝션 방어**:

```python
# security/prompt_guard.py
INJECTION_MARKERS = ["시스템 프롬프트를 무시", "ignore previous instructions", "당신은 이제부터"]

def guard(question: str) -> str | None:
    if any(marker in question.lower() for marker in INJECTION_MARKERS):
        return "죄송합니다. 이 질문은 처리할 수 없습니다."
    return None  # None이면 정상 처리
```

키워드 매칭은 가장 단순한 1차 방어선입니다. 시스템 프롬프트와 사용자 입력을 명확히 분리하는 것(2.6에서 `[근거 조항]`/`[질문]` 영역을 나눈 구조 자체가 1차 방어) 자체도 큰 도움이 되고, 출력 결과를 한 번 더 검증하는 단계는 3단계 고도화에서 보강하는 걸 권장합니다.

### 6.3 GOAD 확장

근시일에는 GOAD 운영 매뉴얼·FAQ를 색인에 포함. 장기적으로는 GOAD DB/로그와 연동해 실제 업무 맥락형 질문에 대응.

---

## 7. 고도화 로드맵 (프로토타입 이후)

| 단계 | 기간 | 핵심 |
|---|---|---|
| 1단계 | 1~3개월 | 하이브리드 검색 튜닝, Multi-Query, RAGAS 상시 평가 |
| 2단계 | 3~6개월 | 자동 재색인 파이프라인, 로그 기반 개선 루프(4.5) 본격 가동, 차별화 기능 운영 수준 완성, 도메인 라우팅 |
| 3단계 | 6~12개월 | RBAC, 감사로그 가명화·보존기간 관리, 개인정보 마스킹, 프롬프트 인젝션 방어 |
| 4단계 | 1년 이후 | LoRA 경량 파인튜닝, GraphRAG 부분 도입, GOAD·전자결재 연계 |

---

## 부록. GOAD 안내봇 하이브리드 확장 (보류)

기존 위즈넛 기반 안내봇의 정해진 질문-답변은 그대로 유지하고, 매칭 실패 시에만 위 RAG 파이프라인으로 폴백시키는 아이디어. 위즈넛이 자체 API/데이터 학습 기능을 제공하는지 확인한 뒤 Hook 방식(API 연동)과 Wrapper 방식(프록시) 중 결정하기로 하고 현재 보류 중.
