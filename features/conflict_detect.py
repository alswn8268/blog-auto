"""조항 간 충돌 탐지 (명세 4.1).

전략: 임베딩 유사도로 "비슷하지만 똑같지는 않은" 조항 쌍만 후보로 좁힌 뒤,
그 후보만 LLM에 "실질적으로 상충하는가?"를 물어 판정한다.
전체 조합을 LLM에 물으면 비용이 감당되지 않으므로 1차 필터가 핵심이다.

실행: python -m features.conflict_detect --doc-title 인사규정
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from itertools import combinations

logger = logging.getLogger(__name__)

JUDGE_PROMPT = """다음 두 조항이 실질적으로 상충하는지 판단하세요.
표현이 다를 뿐 같은 내용이면 "무관"입니다.
같은 상황에 대해 서로 다른 기준·기한·금액·절차를 정하고 있을 때만 "충돌"입니다.

[조항 A] {a_label}
{a_text}

[조항 B] {b_label}
{b_text}

아래 JSON 형식으로만 답하세요.
{{"verdict": "충돌" 또는 "무관", "reason": "한 문장 근거"}}
"""


def cosine_sim(a, b) -> float:
    """넘파이 없이도 도는 코사인 유사도."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def find_conflict_candidates(
    articles: list[dict],
    low: float = 0.70,
    high: float = 0.85,
    *,
    cross_doc_only: bool = False,
) -> list[tuple[str, str, float]]:
    """유사도는 높지만 완전히 같지는 않은 조항 쌍만 후보로 추출한다.

    cross_doc_only=True면 서로 다른 문서 간 충돌(예: 사규 vs 법령)만 본다.
    """
    usable = [a for a in articles if a.get("embedding")]
    if len(usable) != len(articles):
        logger.warning("임베딩이 없는 조항 %d개는 건너뜁니다", len(articles) - len(usable))

    candidates = []
    for a, b in combinations(usable, 2):
        if cross_doc_only and a.get("doc_title") == b.get("doc_title"):
            continue
        sim = cosine_sim(a["embedding"], b["embedding"])
        if low <= sim <= high:
            candidates.append((a["id"], b["id"], sim))
    return sorted(candidates, key=lambda t: t[2], reverse=True)


def _label(article: dict) -> str:
    return f"{article.get('doc_title', '')} {article.get('article_no', '')}"


def judge_conflict(a: dict, b: dict, model: str | None = None) -> dict:
    """후보 한 쌍을 LLM에 판정시킨다. 파싱 실패 시 '판정불가'로 남긴다."""
    from llm.generate import LLMError, complete

    prompt = JUDGE_PROMPT.format(
        a_label=_label(a), a_text=a.get("text", ""), b_label=_label(b), b_text=b.get("text", "")
    )
    try:
        raw = complete(prompt, model=model)
    except LLMError as exc:
        return {"verdict": "판정불가", "reason": str(exc)}

    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            return {"verdict": parsed.get("verdict", "판정불가"), "reason": parsed.get("reason", "")}
        except json.JSONDecodeError:
            pass
    return {"verdict": "판정불가", "reason": raw[:200]}


def detect_conflicts(articles: list[dict], low: float = 0.70, high: float = 0.85,
                     max_pairs: int = 100) -> list[dict]:
    """후보 추출 → LLM 판정 → 충돌로 판정된 쌍만 돌려준다.

    결과를 사전 저장해두고 화면에서는 조회만 하도록 하는 것이 실사용 형태다.
    """
    by_id = {a["id"]: a for a in articles}
    conflicts = []
    for a_id, b_id, sim in find_conflict_candidates(articles, low, high)[:max_pairs]:
        a, b = by_id[a_id], by_id[b_id]
        verdict = judge_conflict(a, b)
        if verdict["verdict"] == "충돌":
            conflicts.append(
                {
                    "a": _label(a),
                    "b": _label(b),
                    "similarity": round(sim, 4),
                    "reason": verdict["reason"],
                }
            )
    return conflicts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="조항 간 충돌 후보를 찾아 LLM으로 판정한다")
    parser.add_argument("--doc-title", default=None, help="특정 문서만 검사 (생략 시 전체)")
    parser.add_argument("--low", type=float, default=0.70)
    parser.add_argument("--high", type=float, default=0.85)
    parser.add_argument("--max-pairs", type=int, default=100)
    parser.add_argument("--out", default="data/conflicts.json")
    args = parser.parse_args()

    from vectordb.setup import get_client
    from vectordb.store import fetch_all_articles

    articles = fetch_all_articles(get_client(), args.doc_title)
    logger.info("조항 %d개 대상", len(articles))
    conflicts = detect_conflicts(articles, args.low, args.high, args.max_pairs)

    from pathlib import Path

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(conflicts, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("충돌 %d건 → %s", len(conflicts), out)


if __name__ == "__main__":
    main()
