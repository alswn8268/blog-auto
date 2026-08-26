"""로그 기반 서비스 개선 루프 (명세 4.5).

로그를 감사 목적으로만 쓰지 않고, 서비스가 스스로 나아지는 데이터로 순환시킨다.

  1) 저신뢰 질문 클러스터링 → 문서 공백 발견
  2) 사용자 피드백(👍/👎) → 골든셋 자동 확장
  3) 버전 태깅(prompt_version·model_version) → 회고적 비교

주의: 이 순환이 성립하려면 질문·답변 로그를 충분히, 오래 갖고 있어야 한다.
이것이 6.2에서 짚은 개인정보 보호 관점의 가장 취약한 지점이므로,
보존기간(RETENTION_DAYS) 안에서만 돌린다는 전제를 깔고 쓴다.
또한 로그를 감사가 아닌 '서비스 개선' 목적으로 쓰려면, 그 목적이
재단 개인정보 처리방침에 명시되어 있는지 먼저 확인해야 한다.
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter, defaultdict

from config import get_settings
from security.audit_log import read_log

logger = logging.getLogger(__name__)

LOW = "하"


# ── 1) 저신뢰 질문 → 문서 공백 발견 ────────────────────────────────────────


def find_low_confidence_questions(log_path: str | None = None) -> list[str]:
    """confidence가 '하'인 질문만 모은다."""
    s = get_settings()
    entries = read_log(log_path or s.audit_log_path)
    return [e["question"] for e in entries if e.get("confidence") == LOW and e.get("question")]


def cluster_questions(questions: list[str], n_clusters: int = 5) -> dict[int, list[str]]:
    """저신뢰 질문을 임베딩해 주제별로 묶는다.

    질문 수가 적으면(클러스터 수 이하) 묶지 않고 하나로 돌려준다.
    scikit-learn이 없으면 단순 키워드 빈도 묶기로 자동 폴백한다.
    """
    if len(questions) <= n_clusters:
        return {0: questions}

    try:
        from sklearn.cluster import KMeans  # 지연 임포트
    except ImportError:
        logger.info("scikit-learn이 없어 키워드 빈도 묶기로 대체합니다")
        return _cluster_by_keyword(questions, n_clusters)

    from embedding.embedder import get_embedder

    vectors = get_embedder().encode(questions).dense
    labels = KMeans(n_clusters=n_clusters, n_init=10, random_state=0).fit_predict(vectors)

    grouped: dict[int, list[str]] = defaultdict(list)
    for q, label in zip(questions, labels):
        grouped[int(label)].append(q)
    return dict(grouped)


def _cluster_by_keyword(questions: list[str], n_clusters: int) -> dict[int, list[str]]:
    """대표 키워드로 묶는 가벼운 대체 구현."""
    keywords = [w for q in questions for w in q.split() if len(w) >= 2]
    top = [w for w, _ in Counter(keywords).most_common(n_clusters)]

    grouped: dict[int, list[str]] = defaultdict(list)
    for q in questions:
        idx = next((i for i, w in enumerate(top) if w in q), len(top))
        grouped[idx].append(q)
    return dict(grouped)


def report_document_gaps(log_path: str | None = None, n_clusters: int = 5) -> list[dict]:
    """관리자 화면용: "이런 질문이 반복되는데 관련 문서가 부족합니다".

    어떤 사규를 다음에 색인해야 할지 우선순위가 여기서 정해진다.
    """
    questions = find_low_confidence_questions(log_path)
    if not questions:
        return []
    clusters = cluster_questions(questions, n_clusters)
    return sorted(
        (
            {"size": len(qs), "sample": qs[:5], "questions": qs}
            for qs in clusters.values()
            if qs
        ),
        key=lambda c: c["size"],
        reverse=True,
    )


# ── 2) 피드백 → 골든셋 확장 후보 ───────────────────────────────────────────


def collect_feedback_candidates(
    audit_log_path: str | None = None, feedback_log_path: str | None = None
) -> dict[str, list[dict]]:
    """👍는 골든셋 추가 후보로, 👎는 검토 큐로 나눈다.

    👍를 받은 고신뢰 답변도 사람이 한 번 검수한 뒤에 골든셋에 넣는다 — 자동 승격은 하지 않는다.
    """
    s = get_settings()
    qa = {e["message_id"]: e for e in read_log(audit_log_path or s.audit_log_path) if e.get("message_id")}
    feedback = read_log(feedback_log_path or s.feedback_log_path)

    result: dict[str, list[dict]] = {"golden_candidates": [], "review_queue": []}
    for fb in feedback:
        entry = qa.get(fb.get("message_id"))
        if not entry:
            continue
        item = {
            "question": entry["question"],
            "answer": entry["answer"],
            "sources": entry.get("sources", []),
            "confidence": entry.get("confidence"),
            "prompt_version": entry.get("prompt_version"),
        }
        if fb.get("verdict") == "positive":
            result["golden_candidates"].append(item)
        else:
            result["review_queue"].append(item)
    return result


# ── 3) 버전 태깅 → 회고적 비교 ─────────────────────────────────────────────

_CONFIDENCE_SCORE = {"상": 1.0, "중": 0.5, "하": 0.0}


def compare_versions(log_path: str | None = None) -> list[dict]:
    """prompt_version·model_version별 신뢰도 평균.

    "프롬프트를 바꾸기 전/후 신뢰도 평균이 어떻게 달라졌는지"를 로그만으로 되짚는다.
    """
    s = get_settings()
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for e in read_log(log_path or s.audit_log_path):
        key = (e.get("prompt_version", "?"), e.get("model_version", "?"))
        buckets[key].append(_CONFIDENCE_SCORE.get(e.get("confidence"), 0.0))

    rows = [
        {
            "prompt_version": pv,
            "model_version": mv,
            "count": len(scores),
            "avg_confidence": round(sum(scores) / len(scores), 3),
        }
        for (pv, mv), scores in buckets.items()
        if scores
    ]
    return sorted(rows, key=lambda r: (r["prompt_version"], r["model_version"]))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="로그에서 개선 지점을 뽑는다")
    parser.add_argument("--clusters", type=int, default=5)
    args = parser.parse_args()

    gaps = report_document_gaps(n_clusters=args.clusters)
    print("\n== 저신뢰 질문 클러스터 (문서 공백 후보) ==")
    for i, g in enumerate(gaps, 1):
        print(f"{i}. {g['size']}건")
        for q in g["sample"]:
            print(f"   - {q}")

    print("\n== 버전별 신뢰도 ==")
    for row in compare_versions():
        print(f"  {row['prompt_version']} / {row['model_version']}: "
              f"{row['avg_confidence']} (n={row['count']})")

    fb = collect_feedback_candidates()
    print(f"\n골든셋 후보 {len(fb['golden_candidates'])}건 / 검토 큐 {len(fb['review_queue'])}건")


if __name__ == "__main__":
    main()
