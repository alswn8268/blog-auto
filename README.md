# 사규·법령 통합 검색 시스템 (Q&A 기반)

사규·법령 원문을 **조항 단위**로 색인하고, 자연어 질문에 **근거 조항을 인용하며** 답하는
RAG(검색 증강 생성) 기반 Q&A 시스템입니다.

- 운영 환경: **내부망 전용** — 외부 클라우드 API에 의존하지 않습니다(임베딩·LLM 모두 로컬 구동).
- 기술 스택: Qdrant · BGE-M3 · BGE reranker · Ollama · Streamlit (모두 오픈소스)

> 기술 명세서: `docs/regulation_qa_tech_spec.md`

---

## 아키텍처

```
[원문: HWP·HWPX·PDF·DOCX]
      │ 파싱            loaders/hwp_loader.py
      ▼
[조항 단위 청킹 + 메타데이터 태깅]   chunking/ · metadata/
      │ 임베딩(BGE-M3)   embedding/embedder.py
      ▼
[Qdrant 벡터DB 색인]     vectordb/
      │
(질문) ─► [하이브리드 검색] ─► [리랭커] ─► [LLM 생성] ─► [Streamlit UI]
          vectordb/store    rerank/     llm/         app/main.py
                                                        │
                                              근거 조항 인용 + 신뢰도 배지
```

---

## 빠른 시작

```bash
# 0) 의존성
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # AUDIT_SALT는 반드시 임의값으로 교체

# 1) Qdrant + Ollama 기동
make up
docker compose exec ollama ollama pull qwen3:8b

# 2) 컬렉션 생성 후 원문 색인
make setup
cp /경로/사규원문/*.hwp data/raw/
make index

# 3) 웹 UI
make app                       # http://localhost:8501
```

샘플 문서로 먼저 확인해보려면:

```bash
python -m pipeline.build_index --dir data/samples
python -m pipeline.query "연차휴가는 며칠인가요?"
```

전 과정을 한 번에 점검하려면 `./scripts/smoke_test.sh`.

### 모델·서버 없이 먼저 돌려보기 (데모 모드)

Qdrant 서버·Ollama·모델 다운로드 없이 파이프라인 배선을 몇 초 만에 확인할 수 있습니다.
인메모리 Qdrant + 해싱 임베더 + 발췌형 스텁 LLM으로 대역을 세운 구성입니다.

```bash
pip install qdrant-client          # 데모에 필요한 유일한 의존성
python scripts/demo.py             # 색인 → 질의 → 보안 → 재색인 → RBAC 순서로 출력
streamlit run scripts/demo_app.py  # 같은 대역으로 실제 UI 띄우기
```

> 대역은 **배선 검증용**이며 검색 품질을 대표하지 않습니다.
> 실제 품질은 real 모델을 붙인 뒤 `python -m eval.run_ragas`로 측정하세요.

Docker로 통째로 띄우려면 `docker compose up -d` (앱 이미지는 `app/Dockerfile`).

---

## 파일명 규칙과 시행일자

파일명만으로 **실제 시행일자**를 뽑아내므로, 개정 이력이 처리일이 아닌 규정 이력과
정확히 맞아떨어집니다.

```
인사규정(2024.03.15. 일부개정).hwp
└ doc_title  └ effective_date  └ revision_type
```

실제 표기 규칙이 다르면 `metadata/filename_parser.py`의 `FILENAME_PATTERN` 하나만
교체하면 됩니다. `tests/test_filename_parser.py`가 그 변경의 파급 범위를 바로 알려줍니다.

---

## 주요 명령

| 명령 | 설명 |
|---|---|
| `make setup` | Qdrant 컬렉션 생성 (`python -m vectordb.setup`) |
| `make index` | `data/raw` 전체 색인 |
| `make reindex` | 변경된 파일의 **바뀐 조항만** 재색인 (cron 등록용) |
| `make app` | Streamlit 실행 |
| `make eval` | RAGAS 평가 |
| `make gaps` | 로그에서 개선 지점(문서 공백·버전 비교) 추출 |
| `make purge` | 보존기간 지난 감사로그 파기 |
| `make test` | 단위 테스트 (모델·DB 없이 실행) |

---

## 디렉터리 구조

```
loaders/        HWP·HWPX·PDF·DOCX 파싱 (1순위 rhwp → 폴백 파서 순차 시도)
metadata/       파일명 → 문서명·시행일자·개정구분·문서종류
chunking/       제n조 단위 청킹, 장/절 추적, 부칙 구분, 안정적 청크 ID
embedding/      BGE-M3 dense + sparse 인코딩
vectordb/       Qdrant 컬렉션 설계·색인·하이브리드 검색(RRF)·이력 관리
rerank/         BGE reranker v2-m3 (0~1 정규화 점수 → 신뢰도 계산에 사용)
llm/            Ollama 연동, 근거 인용 강제 프롬프트
pipeline/       build_index(색인) · query(검색→리랭킹→생성→신뢰도→로그)
features/       조항 충돌 탐지 · 개정 diff · 신뢰도 점수 · 자동 재색인
improvement/    저신뢰 질문 클러스터링 · 피드백 → 골든셋 · 버전별 비교
security/       PII 마스킹 · 프롬프트 가드 · RBAC · 감사로그(가명화·보존기간)
eval/           운영 Q&A → 골든셋 변환, RAGAS 평가
app/            Streamlit UI + 관리자 페이지
```

---

## 차별화 기능

**조항 간 충돌 탐지** (`features/conflict_detect.py`)
임베딩 유사도로 "비슷하지만 똑같지는 않은"(0.70~0.85) 조항 쌍만 후보로 좁힌 뒤,
그 후보만 LLM에 상충 여부를 판정시킵니다. 전체 조합을 LLM에 물으면 비용이 감당되지 않으므로
1차 필터가 핵심입니다.

**개정 이력 diff** (`features/revision_diff.py`)
같은 조항의 시행일자별 버전을 unified diff로 비교합니다. 공백·줄바꿈 차이만으로
'개정됨'이 되지 않도록 정규화 후 비교합니다.

**신뢰도 배지** (`features/confidence.py`)
`0.5 × 리랭커 점수 + 0.5 × 충실도`로 상/중/하를 매깁니다. 매 질문마다 RAGAS를 돌리면 느리므로,
실시간에는 "답변이 실제 근거 조항을 인용했는가"를 대리 지표로 씁니다. 근거에 없는 조항을
지어내면 배지가 '하'로 떨어집니다.

**조항 개정 자동 감지 및 재색인** (`features/auto_reindex.py`)
파일 해시로 변경 파일을 찾고, 조항 단위로 비교해 **실제로 바뀐 조항만** 재임베딩합니다.
기존 조항은 삭제하지 않고 `superseded_by`로 표시만 하므로 개정 이력이 그대로 보존됩니다.
시행일자는 파일명에서 뽑은 실제 값을 씁니다.

```bash
python -m features.auto_reindex --dry-run   # 무엇이 바뀌는지만 확인
```

---

## 평가 (RAGAS)

직원이 운영 중인 Q&A 데이터가 있으면 골든셋을 새로 만들 필요가 없습니다.

```bash
python -m eval.build_golden_set --input data/운영QA.xlsx --colloquial eval/colloquial.json
python -m eval.run_ragas --golden eval/golden_set.json
```

변환 전 두 가지를 반드시 확인하세요.

- **지금도 유효한 답변인가** — 그 사이 조항이 개정됐다면 `ground_truth`도 함께 갱신해야 합니다.
- **질문 표현이 실제 사용자 말투인가** — 운영 Q&A는 정제된 문어체라, 채팅창에 실제로 들어올
  구어체 질문을 `--colloquial`로 섞는 것을 권장합니다.

**목표치: Faithfulness 0.75 이상.** 이 아래로 나오면 청킹·프롬프트를 먼저 의심하세요.

---

## 보안 · 개인정보

네 개 계층으로 나눠 설계했습니다.

| 계층 | 내용 |
|---|---|
| 네트워크 | 내부망 전용 배포, 방화벽에서 사내 IP 대역만 허용, 외부 노출 구간은 Nginx에서 TLS 종료 |
| 애플리케이션 | RBAC(`security/rbac.py`) — 부서별 열람 범위를 **검색 시점 필터**로 제한 |
| 애플리케이션 | 프롬프트 인젝션 1차 방어(`security/prompt_guard.py`) + 프롬프트 영역 분리 |
| 데이터 | 감사로그 가명화·PII 마스킹·보존기간 관리(`security/audit_log.py`) |

감사로그는 그 자체가 **개인정보 처리 행위**이므로 세 가지를 구조에 넣었습니다.

1. 실명 대신 단방향 해시(`AUDIT_SALT` 기반)만 저장 — 실명 복원이 필요하면 매핑 테이블을
   별도로, 감사로그보다 더 엄격한 권한으로 보관합니다.
2. 질문·답변은 PII 마스킹 후 저장합니다.
3. `RETENTION_DAYS`가 지난 로그는 지체 없이 파기합니다(cron: `scripts/crontab.example`).

또한 로그 파일 자체가 개인정보이므로, RBAC과 별개로 `logs/` 디렉터리 접근권한을
관리자로 제한해야 합니다.

> **검토 필요**: 이 시스템은 질문 로그 수집이라는 새로운 개인정보 처리를 추가합니다.
> 재단 개인정보 처리방침에 이 처리가 반영되어 있는지, 그리고 로그를 감사가 아닌
> **서비스 개선** 목적(4.5)으로도 쓰려면 그 목적이 처리방침에 명시되어 있는지 함께
> 확인해야 합니다.

RBAC의 부서 판별은 현재 리버스 프록시가 넣어주는 `X-User-Dept` 헤더를 읽습니다.
헤더는 위조 가능하므로 **운영 전환 시 SSO 서명 검증으로 반드시 교체**해야 합니다.

---

## 로그 기반 개선 루프

관리자 페이지(Streamlit 좌측 `관리자`)에서 확인합니다.

1. **저신뢰 질문 클러스터링** → "이런 질문이 반복되는데 관련 문서가 부족합니다"
   → 다음에 색인할 사규의 우선순위가 정해집니다.
2. **👍/👎 피드백** → 👍는 사람 검수 후 골든셋 추가 후보로, 👎는 검토 큐로.
   골든셋이 실제 사용 데이터로 계속 자랍니다(자동 승격은 하지 않습니다).
3. **버전 태깅** (`prompt_version`·`model_version`) → 프롬프트 변경 전/후 신뢰도 평균을
   로그만으로 되짚어 볼 수 있습니다.

---

## 알려진 한계

- **HWP 파서**: `rhwp`는 최근 공개된 패키지라 API가 바뀔 수 있습니다. 실제 원문으로
  두 파서를 비교해 더 깨끗한 쪽을 `loaders/hwp_loader.py`의 `HWP_LOADERS` 앞자리에 두세요.
- **표·별지서식**: 조항 정규식만으로는 깨질 수 있습니다. 실제 샘플로 반드시 검증이 필요합니다.
- **PII 마스킹**: 정규식은 형식이 정해진 정보(주민번호·전화번호)에만 효과적이며,
  이름·직급처럼 문맥으로 판단되는 정보는 놓칩니다. NER 모델을 2차 필터로 붙이는 것이
  고도화 과제입니다.
- **프롬프트 인젝션 방어**: 키워드 매칭은 1차 방어선일 뿐입니다. 출력 검증 단계 보강이 필요합니다.
- **리랭커**: 한국어 특화 체크포인트가 배포되어 있다면 `RERANK_MODEL`만 바꿔 시도해 보세요.

---

## 테스트

모델·Qdrant·Ollama 없이 순수 로직만 검증합니다.

```bash
pip install pytest && pytest -q
```

파싱·청킹·마스킹·보존기간·신뢰도·재색인 대상 선별·골든셋 변환이 대상입니다.
